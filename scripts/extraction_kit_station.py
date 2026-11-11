"""Passive K01 kit staging geometry; catalog roles are not stock quantities.

Only synthetic, closed article envelopes are constructed. The H01 primitive
adapter is reused; no CAD, workflow execution or inventory store is required.
"""
from pathlib import Path
import ast
import copy
import json
import math
import re
import sys

import assembly_model as assembly
import robot_spec
import tube_carrier_model as primitive

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/extraction-kit-station.shared.json'
SCHEMA = ROOT / 'model/extraction-kit-station.schema.json'
digest = robot_spec.digest
evaluate = robot_spec.evaluate
numeric_shape = primitive.numeric_shape
FORMAT = 'solidcraftbot.extraction-kit-station/1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names.split()), 'Invalid ' + label + ' fields')


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value > 0, 'Positive finite dimension required')
    return value


def catalog(spec):
    """Resolve material identities from exactly the pinned catalog bytes."""
    exact(spec['catalog'], 'source source_sha256', 'catalog reference')
    path = assembly.validate_reference(spec['catalog'], root=ROOT)
    raw = path.read_bytes()
    import hashlib
    require(hashlib.sha256(raw).hexdigest() == spec['catalog']['source_sha256'], 'Catalog changed while reading')
    result = json.loads(raw)
    require(result.get('format') == 'solidcraftbot.extraction-catalog/1', 'Unsupported extraction catalog')
    return result


def parameters(spec, overrides=None):
    require(set(spec['parameters']) == set('outer_w outer_d base_h bottom wall insert_t insert_clearance slot_clearance lid_h lid_overlap lid_side_clearance lid_wall module_gap rear_gap shelf_margin shelf_t handle_width handle_bar handle_thickness carrier_handle_projection carrier_handle_z lid_handle_rise handle_embed handle_approach_distance assumed_finger_width assumed_finger_thickness handle_clearance'.split()), 'Unsupported station parameters')
    for name in overrides or {}:
        require(name in spec['parameters'], 'Unknown parameter override')
        expression = str(spec['parameters'][name]['expression'])
        require(not any(isinstance(n, ast.Name) for n in ast.walk(ast.parse(expression, mode='eval'))), 'Override driving parameters only')
    p = robot_spec.parameters(spec, overrides)
    for name, definition in spec['parameters'].items():
        exact(definition, 'expression unit range description', 'parameter')
        require(definition['unit'] == 'mm' and len(definition['range']) == 2, 'Explicit mm parameter range required')
        for bound in definition['range']:
            number(bound)
        require(definition['range'][0] <= p[name] <= definition['range'][1], 'Parameter outside declared range: ' + name)
        number(p[name])
    require(p['bottom'] < p['base_h'] and p['lid_overlap'] < p['base_h'], 'Invalid container or hood overlap')
    require(p['lid_wall'] < p['lid_h'] and p['insert_t'] + p['bottom'] < p['base_h'], 'Invalid insert or hood thickness')
    require(p['outer_w'] > 2 * (p['wall'] + p['insert_clearance']) and p['outer_d'] > 2 * (p['wall'] + p['insert_clearance']), 'No insert interface remains')
    require(p['handle_width'] < p['outer_w']-2*p['wall'], 'Handle must join the existing wall or roof away from its edges')
    require(p['handle_width'] > 2*p['handle_bar']+p['assumed_finger_width']+2*p['handle_clearance'], 'No declared handle window or finger space remains')
    require(p['carrier_handle_projection'] > p['handle_bar']+2*p['handle_clearance'], 'No front handle window remains')
    require(p['carrier_handle_z'] > p['assumed_finger_thickness']+2*p['handle_clearance'], 'Lower carrier finger space meets the reference floor')
    require(p['carrier_handle_z']+p['handle_thickness']+p['handle_clearance'] < p['base_h']-p['lid_overlap'], 'Closed hood occludes the carrier handle')
    require(p['lid_handle_rise'] > p['handle_bar']+2*p['handle_clearance'], 'No lid handle window remains')
    require(p['handle_embed'] < min(p['wall'], p['lid_wall']), 'Handle fusion must stay within its existing wall or roof')
    require(p['handle_approach_distance'] > p['handle_bar']/2+2*p['handle_clearance'], 'No positive approach space remains')
    return p


def validate(spec):
    exact(spec, 'format id status units recipe catalog parameters native_edit_parameters grid prototype_defaults prototypes modules inserts display_pose poses cases qualification handling limitations', 'station source')
    require(spec['format'] == FORMAT and spec['units'] == {'length': 'mm', 'angle': 'deg'}, 'Unsupported station source or units')
    require(spec['recipe'] == 'common_container_removable_hood_and_interchangeable_3x3_insert_v1', 'Unsupported station recipe')
    require(spec['grid'] == {'rows': 3, 'columns': 3}, 'K01 uses a 3x3 reference insert')
    require(spec['poses'] == ['stored', 'open'] and spec['display_pose'] in spec['poses'], 'Unknown static arrangement')
    require(set(spec['native_edit_parameters']) <= set(spec['parameters']), 'Unknown native edit parameter')
    qualification = spec['qualification']
    exact(qualification, 'manufacturer_dimensions_verified fit_verified fdm_verified chemical_compatibility_verified sop_implemented inventory_implemented sample_storage_implemented gripper_qualified load_qualified article_retention_verified lid_retention_verified robot_motion_implemented', 'qualification')
    require(all(v is False for v in qualification.values()), 'K01 is an unqualified passive concept')
    handling = spec['handling']
    exact(handling, 'recipe status units frame_convention handles unresolved', 'handling concept')
    require(handling['recipe'] == 'integrated_front_loop_and_roof_bridge_v1' and handling['status'] == 'synthetic_unqualified', 'Unsupported or qualified handle contract')
    require(handling['units'] == spec['units'] and handling['frame_convention'] == {'axes': 'right_handed_unit_vectors', 'approach_axis': 'z', 'closing_axis': 'y'}, 'Explicit handle frame convention required')
    exact(handling['handles'], 'carrier lid', 'handle roles')
    frame_ids = []
    for role, descriptor in handling['handles'].items():
        exact(descriptor, 'grasp_frame approach_frame scope', 'handle descriptor')
        require(descriptor['scope'] == ('whole_carrier' if role == 'carrier' else 'lid_only'), 'A lid handle cannot lift a whole kit')
        for name in ('grasp_frame', 'approach_frame'):
            require(isinstance(descriptor[name], str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', descriptor[name]), 'Stable handle frame ID required')
            frame_ids.append(descriptor[name])
    require(len(set(frame_ids)) == 4, 'Handle frames must be distinct')
    require(isinstance(handling['unresolved'], list) and handling['unresolved'] and all(isinstance(v, str) and v for v in handling['unresolved']), 'Handle qualification limits required')
    exact(spec['prototype_defaults'], 'reagent column vessel', 'prototype defaults')
    require(set(spec['prototypes']) == {'small_bottle', 'medium_bottle', 'large_bottle', 'sealed_column_pack', 'sealed_vessel_pack'}, 'Declare the five synthetic envelope prototypes')
    for proto in spec['prototypes'].values():
        require(proto.get('measured_dimensions') is None and proto.get('status') == 'synthetic_assumption', 'Real article dimensions and fit are not qualified')
        if proto.get('shape') == 'cylinder':
            exact(proto, 'shape radius_mm height_mm cap_height_mm measured_dimensions status', 'bottle prototype')
            for name in ('radius_mm', 'height_mm', 'cap_height_mm'):
                number(proto[name])
            require(proto['cap_height_mm'] < proto['height_mm'], 'Closed bottle cap must fit its envelope')
        else:
            exact(proto, 'shape size_mm measured_dimensions status', 'sealed pack prototype')
            require(proto['shape'] == 'box' and len(proto['size_mm']) == 3, 'A sealed pack requires three dimensions')
            for value in proto['size_mm']:
                number(value)
    require(all(p in spec['prototypes'] for p in spec['prototype_defaults'].values()), 'Unknown default envelope')
    require([m['id'] for m in spec['modules']] == ['RNA', 'DNA'], 'Both kit modules required')
    require(len(set(m['insert'] for m in spec['modules'])) == 2 and set(spec['inserts']) == {m['insert'] for m in spec['modules']}, 'Two distinct referenced inserts required')
    for module in spec['modules']:
        exact(module, 'id kit_id insert accent', 'module')
        require(re.fullmatch('#[0-9a-fA-F]{6}', module['accent']) is not None, 'Hex accent required')
        insert = spec['inserts'][module['insert']]
        exact(insert, 'kit_module prototype_by_role', 'insert recipe')
        require(insert['kit_module'] == module['id'], 'Insert references the wrong kit module')
        require(all(v in spec['prototypes'] for v in insert['prototype_by_role'].values()), 'Unknown role envelope')
    require([c['id'] for c in spec['cases']] == ['stored', 'open', 'wide_open'], 'All three static cases required')
    for case in spec['cases']:
        exact(case, 'id overrides display_pose', 'case')
        require(case['display_pose'] in spec['poses'], 'Unknown case pose')
        parameters(spec, case['overrides'])
    require(spec['cases'][0]['display_pose'] == 'stored' and spec['cases'][1]['display_pose'] == spec['cases'][2]['display_pose'] == 'open', 'Case arrangement mismatch')
    p = parameters(spec)
    ensemble(spec, p)
    return spec


def load(path=SOURCE):
    spec = json.loads(Path(path).read_bytes())
    return validate(spec)


def cases(spec):
    return copy.deepcopy(spec['cases'])


def materialize(spec, case_id):
    """Return a separate static source variant, never a pose animation."""
    selected = next((c for c in spec['cases'] if c['id'] == case_id), None)
    require(selected is not None, 'Unknown K01 case')
    result = assembly.parameter_variant(spec, selected['overrides'])
    result['display_pose'] = selected['display_pose']
    return validate(result)


def source_dependencies(spec):
    return [SOURCE, SCHEMA, ROOT / spec['catalog']['source'], ROOT / 'model/assembly-reference.schema.json',
            Path(__file__), ROOT / 'scripts/assembly_model.py', ROOT / 'scripts/robot_spec.py', ROOT / 'scripts/tube_carrier_model.py']


def ensemble(spec, p):
    """One symbolic envelope per distinct catalog material, not per kit role."""
    data = catalog(spec)
    result = []
    for module in spec['modules']:
        require(module['kit_id'] in data['kits'], 'Unknown kit reference')
        kit = data['kits'][module['kit_id']]
        require(kit['analyte'] == module['id'].lower(), 'Kit analyte and module differ')
        recipe = spec['inserts'][module['insert']]['prototype_by_role']
        require(set(recipe) <= set(kit['roles']), 'Unknown catalog kit role')
        materials = {}
        for role, material_id in kit['roles'].items():
            material = data['materials'][material_id]
            require(material['kind'] in spec['prototype_defaults'], 'Unsupported kit material envelope')
            prototype_id = recipe.get(role, spec['prototype_defaults'][material['kind']])
            if material_id in materials:
                require(materials[material_id]['prototype_id'] == prototype_id, 'One material cannot select conflicting envelopes')
                materials[material_id]['roles'].append(role)
                continue
            materials[material_id] = {'material_id': material_id, 'label': material['label'], 'roles': [role],
                'prototype_id': prototype_id, 'prototype': copy.deepcopy(spec['prototypes'][prototype_id]), 'status': 'planned_unobserved'}
        require(len(materials) == spec['grid']['rows'] * spec['grid']['columns'], 'Each kit requires nine deduplicated material envelopes')
        placements = []
        for index, item in enumerate(materials.values()):
            row, column = divmod(index, spec['grid']['columns'])
            proto = item['prototype']
            size = [2 * proto['radius_mm']] * 2 + [proto['height_mm']] if proto['shape'] == 'cylinder' else proto['size_mm']
            slot_w, slot_d = (p['outer_w'] - 2 * p['wall']) / 3, (p['outer_d'] - 2 * p['wall']) / 3
            require(size[0] + 2 * (p['slot_clearance'] + p['insert_clearance']) < slot_w and size[1] + 2 * (p['slot_clearance'] + p['insert_clearance']) < slot_d, 'Article envelopes collide with adjacent slots or insert edges')
            require(p['bottom'] + size[2] < p['base_h'] - p['lid_overlap'] + p['lid_h'] - p['lid_wall'], 'Article envelope does not fit the closed hood assumption')
            placements.append({**item, 'slot_id': 'Slot%02d' % (index + 1), 'row': row, 'column': column, 'envelope_size_mm': list(size)})
        result.append({**copy.deepcopy(module), 'kit_name': kit['name'], 'catalog_number': kit['catalog_number'], 'materials': placements})
    return result


def handle_interfaces(spec, p, module_id, cx, lid_y, lid_z):
    """Derive static candidate frames and disjoint synthetic clearance boxes.

    Tool z points toward the grasp, tool y is the closing direction. These
    frames and spaces do not select a gripper or define an executable motion.
    """
    frames = {}; handles = {}; probes = []
    w, bar, thick = p['handle_width'], p['handle_bar'], p['handle_thickness']
    gap, fw, ft = p['handle_clearance'], p['assumed_finger_width'], p['assumed_finger_thickness']
    distance = p['handle_approach_distance']; projection = p['carrier_handle_projection']
    carrier_z = p['carrier_handle_z']; roof = lid_z+p['lid_h']; rise = p['lid_handle_rise']
    lid_center_y = lid_y+(p['outer_d']+2*(p['lid_side_clearance']+p['lid_wall']))/2
    origins = {'carrier': [cx, -projection+bar/2, carrier_z+thick/2], 'lid': [cx, lid_center_y, roof+rise-bar/2]}
    axes = {'carrier': {'x': [1, 0, 0], 'y': [0, 0, -1], 'z': [0, 1, 0]}, 'lid': {'x': [1, 0, 0], 'y': [0, -1, 0], 'z': [0, 0, -1]}}
    for role in ('carrier', 'lid'):
        source = spec['handling']['handles'][role]
        owner = module_id+('_Container' if role == 'carrier' else '_Lid')
        grasp = module_id+'_'+source['grasp_frame']; approach = module_id+'_'+source['approach_frame']
        for name, origin, purpose in [(grasp, origins[role], 'grasp'), (approach, [v-distance*a for v, a in zip(origins[role], axes[role]['z'])], 'approach')]:
            frames[name] = {'id': name, 'body': owner, 'origin_mm': origin, 'axes': copy.deepcopy(axes[role]), 'units': copy.deepcopy(spec['units']),
                            'status': 'synthetic_unqualified', 'scope': source['scope'], 'purpose': purpose, 'robot_motion_implemented': False}
        handles[role] = {'body': owner, 'grasp_frame': grasp, 'approach_frame': approach, 'scope': source['scope'], 'status': 'synthetic_unqualified'}
    def probe(role, suffix, origin, size, frame='grasp_frame'):
        require(all(v > 0 for v in size), 'Positive synthetic clearance box required')
        probes.append({'id': module_id+'_'+role+'_'+suffix, 'frame_id': handles[role][frame], 'kind': 'box', 'origin_mm': origin, 'size_mm': size,
                       'minimum_clearance_mm': gap, 'units': {'length': 'mm'}, 'status': 'synthetic_unqualified'})
    probe('carrier', 'window', [cx-w/2+bar+gap, -projection+bar+gap, carrier_z], [w-2*(bar+gap), projection-bar-2*gap, thick])
    for label, z in [('finger_low', carrier_z-gap-ft), ('finger_high', carrier_z+thick+gap)]:
        probe('carrier', label, [cx-fw/2, -projection, z], [fw, bar, ft])
    probe('carrier', 'approach', [cx-fw/2, origins['carrier'][1]-distance, carrier_z-gap-ft], [fw, distance-bar/2-gap, thick+2*(gap+ft)], 'approach_frame')
    probe('lid', 'window', [cx-w/2+bar+gap, lid_center_y-thick/2, roof+gap], [w-2*(bar+gap), thick, rise-bar-2*gap])
    for label, y in [('finger_front', lid_center_y-thick/2-gap-ft), ('finger_rear', lid_center_y+thick/2+gap)]:
        probe('lid', label, [cx-fw/2, y, roof+rise-bar], [fw, ft, bar])
    probe('lid', 'approach', [cx-fw/2, lid_center_y-thick/2-gap-ft, roof+rise+gap], [fw, thick+2*(gap+ft), distance-bar/2-gap], 'approach_frame')
    return {'frames': frames, 'handles': handles, 'native_clearance_probes': probes}


def interfaces(spec, p):
    interface = {'width_mm': p['outer_w'] - 2 * (p['wall'] + p['insert_clearance']),
                 'depth_mm': p['outer_d'] - 2 * (p['wall'] + p['insert_clearance']),
                 'thickness_mm': p['insert_t'], 'seat_z_mm': p['bottom'], 'status': 'synthetic_unqualified'}
    modules = {}; frames = {}; probes = []
    for index, module in enumerate(ensemble(spec, p)):
        cx = (-1 if index == 0 else 1) * (p['outer_w'] + p['module_gap']) / 2
        x0 = cx - p['outer_w'] / 2
        lid_x = x0 - p['lid_side_clearance'] - p['lid_wall']
        lid_y = -p['lid_side_clearance'] - p['lid_wall'] if spec['display_pose'] == 'stored' else p['outer_d'] + p['rear_gap']
        lid_z = p['base_h'] - p['lid_overlap'] if spec['display_pose'] == 'stored' else 0
        handling = handle_interfaces(spec, p, module['id'], cx, lid_y, lid_z)
        frames.update(handling['frames']); probes.extend(handling['native_clearance_probes'])
        slots = []
        for item in module['materials']:
            center = [x0+p['wall']+(p['outer_w']-2*p['wall'])*(2*item['column']+1)/6,
                      p['wall']+(p['outer_d']-2*p['wall'])*(2*item['row']+1)/6]
            w, d, h = item['envelope_size_mm']; prefix = module['id'] + '_' + item['slot_id']
            slots.append({'id': item['slot_id'], 'material_id': item['material_id'], 'roles': list(item['roles']),
                          'bodies': [prefix+'_ClosedEnvelope'] + ([prefix+'_ClosedCap'] if item['prototype']['shape'] == 'cylinder' else []),
                          'center_xy_mm': center, 'envelope_bbox_mm': {'min': [center[0]-w/2, center[1]-d/2, p['bottom']], 'max': [center[0]+w/2, center[1]+d/2, p['bottom']+h]},
                          'nominal_slot_clearance_mm': p['slot_clearance'], 'status': 'planned_unobserved'})
        modules[module['id']] = {'kit_id': module['kit_id'], 'insert_id': module['insert'],
            'container_body': module['id']+'_Container', 'insert_body': module['id']+'_Insert', 'lid_body': module['id']+'_Lid',
            'container_shell_bbox_mm': {'min': [x0, 0, 0], 'max': [x0+p['outer_w'], p['outer_d'], p['base_h']]},
            'container_bbox_mm': {'min': [x0, -p['carrier_handle_projection'], 0], 'max': [x0+p['outer_w'], p['outer_d'], p['base_h']]},
            'insert_bbox_mm': {'min': [x0+p['wall']+p['insert_clearance'], p['wall']+p['insert_clearance'], p['bottom']],
                               'max': [x0+p['outer_w']-p['wall']-p['insert_clearance'], p['outer_d']-p['wall']-p['insert_clearance'], p['bottom']+p['insert_t']]},
            'lid_bbox_mm': {'min': [lid_x, lid_y, lid_z], 'max': [lid_x+p['outer_w']+2*(p['lid_side_clearance']+p['lid_wall']), lid_y+p['outer_d']+2*(p['lid_side_clearance']+p['lid_wall']), lid_z+p['lid_h']+p['lid_handle_rise']]},
            'lid_inner_bbox_mm': {'min': [lid_x+p['lid_wall'], lid_y+p['lid_wall'], lid_z], 'max': [lid_x+p['outer_w']+2*p['lid_side_clearance']+p['lid_wall'], lid_y+p['outer_d']+2*p['lid_side_clearance']+p['lid_wall'], lid_z+p['lid_h']-p['lid_wall']]},
            'slots': slots, 'handles': handling['handles']}
    return {'common_insert': interface, 'inserts': {m['insert']: copy.deepcopy(interface) for m in spec['modules']}, 'modules': modules,
            'arrangement': spec['display_pose'], 'fit_qualified': False, 'frames': frames, 'native_clearance_probes': probes}


def expanded(spec, p):
    result = {'id': spec['id'], 'status': spec['status'], 'parameters': spec['parameters'], 'components': [], 'bodies': [], 'operations': [], 'joints': [],
              'catalog_reference': copy.deepcopy(spec['catalog']), 'ensemble': ensemble(spec, p), 'interfaces': interfaces(spec, p), 'static_arrangement': spec['display_pose']}
    def body(name, color, role):
        result['components'].append({'id': name+'_Group', 'grounded': True})
        result['bodies'].append({'id': name, 'component': name+'_Group', 'role': role, 'appearance': {'color': color, 'opacity': 1}})
        return name
    def op(name, target, shape, action='create'):
        result['operations'].append({'id': name, 'body': target, 'action': action, 'shape': shape})
    def box(name, target, size, origin, action='create'):
        op(name, target, {'kind': 'box', 'size': size, 'origin': origin}, action)
    shelf = body('ReferenceFloor', '#c8c5bd', 'illustrative_reference_floor')
    box('ReferenceFloorBox', shelf, ['2*outer_w+module_gap+2*(lid_side_clearance+lid_wall+shelf_margin)',
        '2*outer_d+rear_gap+3*(lid_side_clearance+lid_wall)+2*shelf_margin', 'shelf_t'],
        ['-outer_w-module_gap/2-lid_side_clearance-lid_wall-shelf_margin', '-lid_side_clearance-lid_wall-shelf_margin', '-shelf_t'])
    for index, module in enumerate(result['ensemble']):
        tag = module['id']; cx = ('-' if index == 0 else '') + '(outer_w+module_gap)/2'
        x0 = f'({cx})-outer_w/2'
        shell = body(tag + '_Container', '#e2e6e8', 'passive_container')
        box(tag+'_ContainerOuter', shell, ['outer_w', 'outer_d', 'base_h'], [x0, 0, 0])
        box(tag+'_ContainerInside', shell, ['outer_w-2*wall', 'outer_d-2*wall', 'base_h'], [f'({x0})+wall', 'wall', 'bottom'], 'cut')
        box(tag+'_CarrierHandleOuter', shell, ['handle_width', 'carrier_handle_projection+handle_embed', 'handle_thickness'],
            [f'({cx})-handle_width/2', '-carrier_handle_projection', 'carrier_handle_z'], 'join')
        box(tag+'_CarrierHandleWindow', shell, ['handle_width-2*handle_bar', 'carrier_handle_projection-handle_bar', 'handle_thickness+0.2'],
            [f'({cx})-handle_width/2+handle_bar', '-carrier_handle_projection+handle_bar', 'carrier_handle_z-0.1'], 'cut')
        insert = body(tag + '_Insert', module['accent'], 'interchangeable_insert')
        box(tag+'_InsertPlate', insert, ['outer_w-2*(wall+insert_clearance)', 'outer_d-2*(wall+insert_clearance)', 'insert_t'],
            [f'({x0})+wall+insert_clearance', 'wall+insert_clearance', 'bottom'])
        for item in module['materials']:
            prefix = tag + '_' + item['slot_id']; proto = item['prototype']
            x = f'({x0})+wall+(outer_w-2*wall)*{2*item["column"]+1}/6'
            y = f'wall+(outer_d-2*wall)*{2*item["row"]+1}/6'
            article = body(prefix+'_ClosedEnvelope', '#d5e1e9' if tag == 'RNA' else '#e3d9e9', 'closed_synthetic_article_envelope')
            if proto['shape'] == 'cylinder':
                r, h, cap_h = proto['radius_mm'], proto['height_mm'], proto['cap_height_mm']
                op(prefix+'_Slot', insert, {'kind': 'cylinder', 'radius': f'{r}+slot_clearance', 'height': 'insert_t+0.2', 'origin': [x, y, 'bottom-0.1']}, 'cut')
                op(prefix+'_Bottle', article, {'kind': 'cylinder', 'radius': r, 'height': h-cap_h, 'origin': [x, y, 'bottom']})
                cap = body(prefix+'_ClosedCap', module['accent'], 'closed_synthetic_article_cap')
                op(prefix+'_Cap', cap, {'kind': 'cylinder', 'radius': r, 'height': cap_h, 'origin': [x, y, f'bottom+{h-cap_h}']})
            else:
                w, d, h = proto['size_mm']
                box(prefix+'_Slot', insert, [f'{w}+2*slot_clearance', f'{d}+2*slot_clearance', 'insert_t+0.2'],
                    [f'({x})-{w}/2-slot_clearance', f'({y})-{d}/2-slot_clearance', 'bottom-0.1'], 'cut')
                box(prefix+'_SealedPack', article, [w, d, h], [f'({x})-{w}/2', f'({y})-{d}/2', 'bottom'])
        lid = body(tag + '_Lid', module['accent'], 'removable_hood')
        ly = '-lid_side_clearance-lid_wall' if spec['display_pose'] == 'stored' else 'outer_d+rear_gap'
        lz = 'base_h-lid_overlap' if spec['display_pose'] == 'stored' else '0'
        box(tag+'_HoodOutside', lid, ['outer_w+2*(lid_side_clearance+lid_wall)', 'outer_d+2*(lid_side_clearance+lid_wall)', 'lid_h'],
            [f'({x0})-lid_side_clearance-lid_wall', ly, lz])
        box(tag+'_HoodInside', lid, ['outer_w+2*lid_side_clearance', 'outer_d+2*lid_side_clearance', 'lid_h-lid_wall+0.1'],
            [f'({x0})-lid_side_clearance', f'({ly})+lid_wall', f'({lz})-0.1'], 'cut')
        lid_center_y = f'({ly})+(outer_d+2*(lid_side_clearance+lid_wall))/2'
        box(tag+'_LidHandleOuter', lid, ['handle_width', 'handle_thickness', 'lid_handle_rise+handle_embed'],
            [f'({cx})-handle_width/2', f'({lid_center_y})-handle_thickness/2', f'({lz})+lid_h-handle_embed'], 'join')
        box(tag+'_LidHandleWindow', lid, ['handle_width-2*handle_bar', 'handle_thickness+0.2', 'lid_handle_rise-handle_bar'],
            [f'({cx})-handle_width/2+handle_bar', f'({lid_center_y})-handle_thickness/2-0.1', f'({lz})+lid_h'], 'cut')
    for operation in result['operations']:
        shape = numeric_shape(operation['shape'], p)
        for v in shape.get('size', []) + [shape[k] for k in ('radius', 'height') if k in shape]:
            number(v)
    return result


def pose(spec, p, name=None):
    require((name or spec['display_pose']) == spec['display_pose'], 'Materialize a separate static case to change the hood arrangement')
    return {}


def validate_pose(source, values):
    require(source['joints'] == [] and values == {}, 'K01 has no joint or motion channel')


def samples(spec, p):
    return [{'id': spec['display_pose'], 'values_mm': {}}]


def displacement(source, component, values):
    validate_pose(source, values)
    return [0, 0, 0]


def check_interface_geometry(spec, p, measurements):
    by_name = {m['body']: m for m in measurements}
    contract = interfaces(spec, p); expected = contract['common_insert']
    checks = []
    def bbox(name):
        require(name in by_name, 'Missing native body: ' + name)
        return by_name[name]['bbox']
    def matches(actual, wanted):
        return max(abs(actual[edge][i]-wanted[edge][i]) for edge in ('min', 'max') for i in range(3)) < 1e-7
    for module_id, module in contract['modules'].items():
        name = module['insert_body']; bb = bbox(name)
        size = [b-a for a, b in zip(bb['min'], bb['max'])]
        checks.append({'id': name, 'passed': matches(bb, module['insert_bbox_mm']) and max(abs(a-b) for a, b in zip(size, [expected['width_mm'], expected['depth_mm'], expected['thickness_mm']])) < 1e-7 and abs(bb['min'][2]-expected['seat_z_mm']) < 1e-7,
                       'size_mm': size, 'seat_z_mm': bb['min'][2], 'fit_qualified': False})
        for kind in ('container', 'lid'):
            actual = bbox(module[kind+'_body'])
            checks.append({'id': module_id+'_'+kind+'_placement', 'passed': matches(actual, module[kind+'_bbox_mm']), 'bbox_mm': actual, 'fit_qualified': False})
        for slot in module['slots']:
            boxes = [bbox(body) for body in slot['bodies']]
            actual = {edge: [operation(b[edge][i] for b in boxes) for i in range(3)] for edge, operation in [('min', min), ('max', max)]}
            clearance = module['lid_inner_bbox_mm']['max'][2]-actual['max'][2] if spec['display_pose'] == 'stored' else None
            fits_hood = clearance > 0 if clearance is not None else True
            checks.append({'id': module_id+'_'+slot['id']+'_article_placement', 'passed': matches(actual, slot['envelope_bbox_mm']) and fits_hood,
                           'material_id': slot['material_id'], 'bodies': slot['bodies'], 'bbox_mm': actual, 'closed_hood_top_clearance_mm': clearance,
                           'nominal_slot_clearance_mm': slot['nominal_slot_clearance_mm'], 'fit_qualified': False})
    return checks


def geometry_checks(spec, p):
    modules = ensemble(spec, p)
    return [{'id': 'catalog_material_deduplication', 'passed': all(len(m['materials']) == 9 for m in modules), 'symbolic_envelopes_per_module': [len(m['materials']) for m in modules]},
            {'id': 'shared_insert_interface', 'passed': len({json.dumps(v, sort_keys=True) for v in interfaces(spec, p)['inserts'].values()}) == 1, 'fit_qualified': False}]


def solidcraft_commands(spec, p):
    commands = primitive.solidcraft_commands(spec, p, provider=sys.modules[__name__])
    for command in commands:
        if command['command'] == 'document.metadata.set':
            original = command['params']['values'].pop('org.solidcraftbot.tube-carrier')
            command['params']['values']['org.solidcraftbot.extraction-kit-station'] = {**original, 'catalog': copy.deepcopy(spec['catalog']), 'static_arrangement': spec['display_pose'], 'fit_qualified': False}
    return commands
