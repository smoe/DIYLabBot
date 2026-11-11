"""Portable hollow glassware, removable closures and geometric access references."""
import copy
import ast
import json
import math
from pathlib import Path
import re

import assembly_model as assembly
import robot_spec as robot
import tube_carrier_model as portable
import marker_label

ROOT = robot.ROOT
SOURCE = ROOT / 'model/lab-glassware.shared.json'
digest = robot.digest
evaluate = robot.evaluate
RECIPES = {
    'beaker': 'hollow_beaker_with_pour_spout/1',
    'funnel': 'open_conical_funnel_with_continuous_stem/1',
    'bottle': 'hollow_shoulder_bottle_with_removable_closure/1',
    'measuring_cylinder': 'hollow_measuring_cylinder_with_hexagonal_foot/1',
}
FIELDS = {
    'beaker': set('diameter height wall bottom spout_length spout_width spout_depth outer_radius inner_radius'.split()),
    'funnel': set('diameter bowl_height stem_length stem_diameter wall outer_radius inner_radius stem_radius outlet_radius height'.split()),
    'bottle': set('diameter body_height shoulder_height wall bottom outer_radius inner_radius shoulder_top height'.split()),
    'measuring_cylinder': set('diameter height wall base_height floor_thickness base_across_flats spout_length spout_width spout_depth outer_radius inner_radius bottom base_radius'.split()),
}
CLOSURES = {
    'screw_cap': ('removable_screw_cap_envelope/1', set('neck_diameter neck_height neck_wall neck_radius mouth_radius cap_skirt cap_wall cap_clearance seal_gap closure_radius'.split())),
    'glass_stopper': ('removable_glass_stopper_envelope/1', set('neck_diameter neck_height neck_wall neck_radius mouth_radius stopper_depth stopper_grip_height seal_gap stopper_clearance stopper_taper stopper_overhang closure_radius'.split())),
}


def finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Finite numeric value required: ' + name)
    return value


def validate_definitions(definitions, names):
    if set(definitions) != names:
        raise ValueError('Only implemented parameter fields are supported')
    for name, parameter in definitions.items():
        if (set(parameter) != {'expression', 'unit', 'range', 'description'}
                or parameter['unit'] != 'mm' or not parameter['description']):
            raise ValueError('Explicit length parameter definition required: ' + name)
        bounds = parameter['range']
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError('Parameter range required: ' + name)
        lo, hi = (finite(v, name) for v in bounds)
        if lo <= 0 or hi < lo:
            raise ValueError('Positive ordered parameter range required: ' + name)


def load(path=SOURCE):
    catalog = json.loads(Path(path).read_text(encoding='utf-8'))
    fields = {'format', 'id', 'units', 'status', 'material', 'references', 'families', 'closures', 'items', 'limitations'}
    if set(catalog) != fields or catalog['format'] != 'solidcraftbot.lab-glassware/2':
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
        if set(definition) != {'recipe', 'parameters', 'sizes'} or definition['recipe'] != RECIPES[family]:
            raise ValueError('Unsupported glassware recipe: ' + family)
        validate_definitions(definition['parameters'], FIELDS[family])
        if not isinstance(definition['sizes'], dict) or not definition['sizes']:
            raise ValueError('Explicit named size variants required')
        for size in definition['sizes'].values():
            if set(size) != {'nominal_volume_ml','overrides'}:
                raise ValueError('A size variant contains only nominal volume and dimension overrides')
            if (family=='funnel') != (size['nominal_volume_ml'] is None):
                raise ValueError('Funnels have a diameter, not a nominal storage volume')
            if (not isinstance(size['overrides'],dict) or set(size['overrides'])-FIELDS[family]
                    or any(type(v) not in (int,float) for v in size['overrides'].values())):
                raise ValueError('Size overrides must refer to independent family dimensions')
    if not catalog['closures']:
        raise ValueError('Shared closure definitions required')
    for identity, closure in catalog['closures'].items():
        if set(closure) != {'kind','recipe','parameters'} or closure['kind'] not in CLOSURES:
            raise ValueError('Unsupported shared closure definition: '+identity)
        recipe, names = CLOSURES[closure['kind']]
        if closure['recipe'] != recipe:
            raise ValueError('Unsupported closure recipe')
        validate_definitions(closure['parameters'], names)
        for field in closure['parameters'].values():
            dependencies = {n.id for n in ast.walk(ast.parse(str(field['expression']),mode='eval')) if isinstance(n,ast.Name)}
            if dependencies - names:
                raise ValueError('Closure dimensions must be independent of vessel body size')
    for identity, reference in catalog['references'].items():
        expected = {'url', 'accessed', 'manufacturer', 'part', 'description', 'nominal_volume_ml',
                    'reference_graduations_ml', 'outer_dimensions_mm'}
        if set(reference)-{'verified_url'} != expected or not reference['url'].startswith('https://'):
            raise ValueError('Documentary product reference required: ' + identity)
        dimensions = reference['outer_dimensions_mm']
        if dimensions is not None:
            if set(dimensions) != {'height','diameter','base_across_flats'}:
                raise ValueError('Explicit documented/unknown outer dimensions required')
            for key,value in dimensions.items():
                if value is not None and finite(value,key)<=0:
                    raise ValueError('Documented dimensions must be positive')
        nominal = finite(reference['nominal_volume_ml'], identity)
        marks = reference['reference_graduations_ml']
        if set(marks) != {'first', 'last', 'step'}:
            raise ValueError('Reference graduation interval required')
        first = marks['first']
        last, step = (finite(marks[k], k) for k in ('last', 'step'))
        if not 0 < last <= nominal or step <= 0 or (first is not None and not 0 < finite(first,'first') <= last):
            raise ValueError('Reference graduations must lie within the nominal volume')
    for identity, item in catalog['items'].items():
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', identity):
            raise ValueError('Stable glassware item ID required')
        if set(item) != {'family', 'size', 'label', 'closure', 'reference'}:
            raise ValueError('Unsupported glassware item fields: ' + identity)
        if item['family'] not in RECIPES or not item['label']:
            raise ValueError('Implemented family and label required')
        allowed = set(catalog['closures']) if item['family'] == 'bottle' else {'none'}
        if item['closure'] not in allowed:
            raise ValueError('Closure does not match the vessel family: ' + identity)
        if item['size'] not in catalog['families'][item['family']]['sizes']:
            raise ValueError('Unknown named glassware size: '+identity)
        spec = materialize(catalog, identity)
        if item['reference'] is not None:
            if item['reference'] not in catalog['references']:
                raise ValueError('Unknown product reference: ' + identity)
            ref = catalog['references'][item['reference']]
            if ref['nominal_volume_ml'] != spec['item']['nominal_volume_ml']:
                raise ValueError('Nominal volume differs from its documentary reference')
            dims = ref['outer_dimensions_mm']
            if dims is not None and dims['height'] is not None and parameters(spec)['height'] != dims['height']:
                raise ValueError('Catalog height differs from the documented product height')
    return catalog


def materialize(catalog, identity, state=None, overrides=None, context=None, label=None):
    """Instantiate a family once; variants contain only driving dimension overrides."""
    if identity not in catalog['items']:
        raise ValueError('Unknown glassware item: ' + identity)
    item = copy.deepcopy(catalog['items'][identity])
    size = catalog['families'][item['family']]['sizes'][item['size']]
    item['nominal_volume_ml'] = size['nominal_volume_ml']
    closure = None if item['closure']=='none' else copy.deepcopy(catalog['closures'][item['closure']])
    state = ('closed' if item['family'] == 'bottle' else 'open') if state is None else state
    if type(state) is not str or state not in ({'open', 'closed'} if item['family'] == 'bottle' else {'open'}):
        raise ValueError('Unsupported glassware configuration: ' + str(state))
    spec = {'id': identity + '_' + state, 'item_id': identity, 'item': copy.deepcopy(item),
            'state': state, 'status': catalog['status'], 'closure': closure,
            'label': marker_label.validate(label),
            'parameters': copy.deepcopy(catalog['families'][item['family']]['parameters'])}
    if closure is not None:
        spec['parameters'].update(copy.deepcopy(closure['parameters']))
    if overrides is not None and set(overrides)-FIELDS[item['family']]:
        raise ValueError('Size overrides cannot alter shared neck/closure dimensions')
    spec = assembly.parameter_variant(spec, size['overrides'])
    spec = assembly.parameter_variant(spec, overrides, context)
    if item['family'] == 'bottle':
        # These offsets describe two static configurations, not a removal trajectory.
        closed_bottom = ('height-cap_skirt+seal_gap' if closure['kind'] == 'screw_cap'
                         else 'height-stopper_depth')
        for name, expression in {
            'closure_x': 'outer_radius+closure_radius+20' if state == 'open' else 0,
            'closure_z': '-(' + closed_bottom + ')' if state == 'open' else 0,
        }.items():
            spec['parameters'][name] = {'expression': expression, 'unit': 'mm', 'range': [-300, 300],
                                        'description': 'Derived static closure configuration offset'}
    # SolidCraft declares parameters sequentially; reuse the common evaluator's
    # dependency order after composing body and shared closure definitions.
    values = parameters(spec)
    spec['parameters'] = {name:spec['parameters'][name] for name in values}
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
    if family in {'beaker','measuring_cylinder'}:
        if (p['bottom'] >= p['height'] - p['spout_depth'] or p['spout_width'] <= 2*p['wall']
                or p['spout_depth'] <= 2*p['wall'] or p['spout_width'] >= p['diameter']):
            raise ValueError('Beaker requires a bottom and a genuinely open pouring trough')
        if family=='measuring_cylinder' and p['base_across_flats']<=p['diameter']+2:
            raise ValueError('Measuring cylinder requires a wider hexagonal foot')
    elif family == 'funnel':
        if p['outlet_radius'] <= 0 or p['inner_radius'] <= p['outlet_radius']:
            raise ValueError('Funnel requires an open stem below a wider inlet')
    else:
        if (p['mouth_radius'] <= 1 or p['inner_radius'] <= p['neck_radius']
                or p['bottom'] >= p['body_height']
                or p['neck_wall'] >= p['neck_radius']):
            raise ValueError('Bottle shoulder, neck, bottom and closure must leave a real cavity')
        if spec['closure']['kind']=='screw_cap' and p['cap_skirt']>=p['neck_height']:
            raise ValueError('Shared cap skirt must fit the shared neck')
        if spec['closure']['kind']=='glass_stopper' and (p['stopper_depth']>=p['neck_height'] or p['mouth_radius']<=p['stopper_clearance']+p['stopper_taper']):
            raise ValueError('Shared stopper must fit the shared neck')
    nominal = spec['item']['nominal_volume_ml']
    if nominal is not None:
        if finite(nominal, 'nominal_volume_ml') <= 0 or nominal > cavity_volume_ml(spec, p):
            raise ValueError('Nominal volume does not fit below the modeled access/spout region')
    marker_label.build(spec,p)  # Reject labels which cannot fit the selected surface.
    return p


def cavity_segments(spec, p):
    """Axial clear-space frustums; the beaker core ends below its spout root."""
    family = spec['item']['family']
    if family in {'beaker','measuring_cylinder'}:
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
        if family in {'beaker','measuring_cylinder'}:
            result['pour_lip'] = frame([p['outer_radius']+p['spout_length'], 0, p['height']], axis=(1, 0, 0))
        else:
            top = (p['height']+p['seal_gap']+p['cap_wall'] if spec['closure']['kind'] == 'screw_cap'
                   else p['height']+p['seal_gap']+p['stopper_grip_height'])
            result['closure_grip_axis'] = frame([p['closure_x'], 0, top+p['closure_z']])
    return result


def accessible_mouth(spec, p):
    frame = interfaces(spec, p)['mouth']
    if not frame['accessible']:
        raise ValueError('Remove the closure before requesting pipette access')
    return frame


def closure_profile(spec):
    """A closure in mouth-local coordinates, independent of bottle body dimensions."""
    if spec['closure'] is None:
        return None
    if spec['closure']['kind']=='screw_cap':
        return [['neck_radius+cap_clearance','-cap_skirt+seal_gap'],
                ['closure_radius','-cap_skirt+seal_gap'], ['closure_radius','seal_gap+cap_wall'],
                [0,'seal_gap+cap_wall'], [0,'seal_gap'], ['neck_radius+cap_clearance','seal_gap']]
    return [[0,'-stopper_depth'], ['mouth_radius-stopper_clearance-stopper_taper','-stopper_depth'],
            ['mouth_radius-stopper_clearance','seal_gap'], ['closure_radius','seal_gap'],
            ['closure_radius','seal_gap+stopper_grip_height'], [0,'seal_gap+stopper_grip_height']]


def closure_signature(spec,p):
    points = closure_profile(spec)
    if points is None:
        return None
    return {'id':spec['item']['closure'], 'kind':spec['closure']['kind'],
            'parameters_mm':{name:p[name] for name in spec['closure']['parameters']},
            'mouth_local_profile_rz_mm':[[evaluate(v,p) for v in point] for point in points]}


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
    if family in {'beaker','measuring_cylinder'}:
        base = 'base_height-0.1' if family=='measuring_cylinder' else 0
        profile('HollowBeaker' if family=='beaker' else 'HollowMeasuringCylinder', [[0, base], ['outer_radius', base], ['outer_radius', 'height'],
                                 ['inner_radius', 'height'], ['inner_radius', 'bottom'], [0, 'bottom']])
        if family=='measuring_cylinder':
            result['operations'].append({'id':'HexagonalGlassFoot','body':'Vessel','action':'join',
                'shape':{'kind':'polygon_prism','plane':'XY','offset':0,'depth':'base_height+0.1',
                         'points':[['base_radius',0],['base_radius/2','base_across_flats/2'],
                                   ['-base_radius/2','base_across_flats/2'],['-base_radius',0],
                                   ['-base_radius/2','-base_across_flats/2'],['base_radius/2','-base_across_flats/2']]}})
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
        screw = spec['closure']['kind'] == 'screw_cap'
        body('Closure', component='ClosureGroup', color='#346a91' if screw else '#a6c8cf',
             opacity=1 if screw else .7, role='screw_cap_envelope' if screw else 'glass_stopper_envelope')
        profile('RemovableClosure', [[r, 'height+('+str(z)+')+closure_z'] for r, z in closure_profile(spec)],
                target='Closure', center='closure_x')
    strokes, info = marker_label.build(spec,p)
    for index,shape in enumerate(strokes):
        name = 'MarkerInk%04d'%index
        body(name,color=info['color'],opacity=1,role='marker_ink')
        result['operations'].append({'id':name,'body':name,'action':'create','shape':shape})
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
                'item': spec.get('item_id'), 'configuration': spec.get('state'),
                'closure':spec.get('item',{}).get('closure'), 'marker_label':spec.get('label'),
                'status': spec['status']}}}
    commands.append({'command': 'browser.visibility', 'params': {'folder': 'sketches', 'visible': False}})
    return commands


def cases(catalog):
    return [(identity, state) for identity, item in catalog['items'].items()
            for state in (('closed', 'open') if item['family'] == 'bottle' else ('open',))]


def case_id(identity, state):
    return identity + '_' + state


def resolve_reference(ref, overrides=None, context=None, label=None):
    path = assembly.validate_reference(ref)
    catalog = load(path)
    candidates = [(identity, state) for identity, state in cases(catalog)
                  if case_id(identity, state) == ref.get('case')]
    if len(candidates) != 1:
        raise ValueError('Select an explicit glassware item/configuration through its report case')
    return materialize(catalog, *candidates[0], overrides=overrides, context=context,label=label)


def overview(catalog):
    """Derived contact sheet; item geometry is compiled from catalog references."""
    selected = [('beaker_250','open','DNA 01'), ('funnel_60','open','Buffer'),
                ('measuring_cylinder_5','open','QC'), ('screw_bottle_100','closed','A'),
                ('screw_bottle_500','closed','B'), ('screw_bottle_250','open','Buffer A'),
                ('stopper_bottle_250','open','EtOH')]
    spec = {'id': 'LaboratoryGlasswareOverview', 'status': catalog['status'], 'parameters': {}}
    result = {'id': spec['id'], 'status': spec['status'], 'parameters': {}, 'components': [],
              'bodies': [], 'operations': [], 'joints': []}
    placements, cursor = [], 0
    for index, (identity, state, text) in enumerate(selected):
        item = materialize(catalog, identity, state,label={'text':text})
        p = parameters(item)
        prefix = 'Item' + str(index) + '_'
        x = cursor + max(p['outer_radius'],p.get('base_radius',0))
        placements.append({'reference': {'source': str(SOURCE.relative_to(ROOT)), 'case': case_id(identity, state)},
                           'translation_mm': [x, 0, 0], 'label': item['item']['label'],
                           'marker_label':item['label'], 'state': state})
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
            elif shape['kind']=='polygon_prism':
                shape['offset'] = evaluate(shape['offset'], p)
                shape['depth'] = evaluate(shape['depth'], p)
                shape['points'] = [[evaluate(a, p)+x, evaluate(b, p)] for a, b in shape['points']]
            elif shape['kind']=='cylinder':
                shape = portable.numeric_shape(shape,p)
                shape['origin'][0] += x
            else:
                raise ValueError('Unsupported derived overview primitive')
            result['operations'].append({**operation, 'id': prefix+operation['id'],
                                         'body': prefix+operation['body'], 'shape': shape})
        right = max(p['outer_radius']+p.get('spout_length', 0),p.get('base_radius',0),
                    p.get('closure_x', 0)+p.get('closure_radius', 0))
        cursor = x + right + 28
    return spec, result, placements
