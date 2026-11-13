"""One source-selected K01 carrier in two static synthetic storage placements.

Leading geometry remains in K01. This composition projects its explicit RNA
body interface, references furniture types and applies one translation to all
selected construction operations, frames and clearance probes. No motion or
stock ledger is implemented here.
"""
from pathlib import Path
import copy
import hashlib
import json
import math
import re
import sys

import assembly_model as assembly
import extraction_kit_station as kit
import furniture_model as furniture
import robot_spec as robot
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/kit-storage-s01.shared.json'
SCHEMA = ROOT/'model/kit-storage-s01.schema.json'
FORMAT = 'solidcraftbot.synthetic-kit-storage/1'
DRIVING = 'shelf_margin_x shelf_margin_front shelf_margin_back support_t support_top place_gap nest_clearance nest_guide_t nest_guide_h'.split()
DERIVED = ('carrier_width', 'carrier_depth', 'carrier_height')
digest = robot.digest
evaluate = robot.evaluate
numeric_shape = portable.numeric_shape


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, fields, name):
    require(isinstance(value, dict) and set(value) == set(fields.split()), 'Invalid '+name+' fields')


def read(ref):
    exact(ref, 'source source_sha256', 'pinned source')
    path = assembly.validate_reference(ref, root=ROOT)
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref['source_sha256'], 'Source changed while reading: '+ref['source'])
    return json.loads(raw)


def selected_carrier(spec):
    """Select by declared interface IDs, never a native name-prefix heuristic."""
    ref = spec['sources']['kit']; read(ref)
    source_spec = kit.materialize(kit.load(assembly.validate_reference(ref, root=ROOT)), spec['carrier']['source_case'])
    p = kit.parameters(source_spec); source = kit.expanded(source_spec, p)
    contract = source['interfaces']; module_id = spec['carrier']['module_id']
    require(module_id in contract['modules'], 'Unknown source kit module')
    interface = contract['modules'][module_id]
    identities = [interface['container_body'], interface['insert_body'], interface['lid_body']]
    identities += [body for slot in interface['slots'] for body in slot['bodies']]
    require(len(set(identities)) == len(identities), 'Selected carrier has aliased source bodies')
    available = {body['id'] for body in source['bodies']}
    require(set(identities) <= available, 'Selected interface refers to missing geometry')
    module = next(m for m in source['ensemble'] if m['id'] == module_id)
    shell = interface['container_shell_bbox_mm']
    datum = [(shell['min'][0]+shell['max'][0])/2, shell['min'][1], shell['min'][2]]
    return {'spec': source_spec, 'p': p, 'source': source, 'interface': interface,
            'module': module, 'body_ids': identities, 'datum': datum, 'contract': contract}


def parameters(spec, overrides=None):
    require(set(spec['parameters']) in (set(DRIVING), set(DRIVING) | set(DERIVED)), 'Unsupported storage parameters')
    require(not set(overrides or {})-set(DRIVING), 'Only declared driving storage parameters may be overridden')
    definitions = {name: spec['parameters'][name] for name in DRIVING}
    p = robot.parameters({'parameters': definitions}, overrides)
    for name, definition in definitions.items():
        exact(definition, 'expression unit range description', 'parameter')
        bounds = definition['range']
        require(definition['unit'] == 'mm' and len(bounds) == 2 and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in bounds) and bounds[0] <= bounds[1], 'Finite positive mm parameter range required')
        require(bounds[0] <= p[name] <= bounds[1], 'Storage parameter outside declared range: '+name)
    carrier = selected_carrier(spec); box = carrier['interface']['container_shell_bbox_mm']
    values = {'carrier_width': box['max'][0]-box['min'][0], 'carrier_depth': box['max'][1]-box['min'][1],
              'carrier_height': carrier['interface']['lid_bbox_mm']['max'][2]-carrier['datum'][2]}
    if set(DERIVED) <= set(spec['parameters']):
        for name, value in values.items():
            require(robot.evaluate(spec['parameters'][name]['expression'], {}) == value, 'Derived carrier parameter differs from its source')
    p.update(values)
    require(p['support_top'] > p['support_t'], 'No positive support elevation remains')
    require(p['shelf_margin_x'] > p['nest_clearance']+p['nest_guide_t'] and p['shelf_margin_back'] > p['nest_clearance']+p['nest_guide_t'], 'Fixed guides must lie on their support')
    require(p['nest_guide_h'] < min(carrier['p']['carrier_handle_z'], carrier['p']['base_h']-carrier['p']['lid_overlap']), 'Guide obstructs the source carrier handle or hood')
    require(p['nest_clearance'] >= carrier['p']['handle_clearance'], 'Nest clearance cannot reduce the source synthetic margin')
    return p


def validate(spec):
    leading = {key: value for key, value in spec.items() if key != '_source'}
    exact(leading, 'format id status units sources parameters carrier locations nest display_case cases measured_dimensions qualification limitations', 'storage source')
    require(spec['format'] == FORMAT and spec['units'] == {'length': 'mm', 'angle': 'deg'}, 'Unsupported storage source or units')
    require(set(spec['parameters']) == set(DRIVING), 'Leading source cannot duplicate derived K01 dimensions')
    exact(spec['sources'], 'environment furniture furnishings kit', 'source layers')
    environment = read(spec['sources']['environment'])
    require(environment.get('format') == 'solidcraftbot.synthetic-environment/1' and environment.get('extent') == 'unbounded' and environment.get('geometry') == 'none', 'Unbounded environment without shell required')
    require(environment.get('units') == spec['units'] and not set(environment)-{'format', 'id', 'units', 'extent', 'geometry', 'world_frame', 'purpose'}, 'Environment cannot add hidden geometry')
    furniture.validate_catalog(read(spec['sources']['furniture']))
    exact(spec['carrier'], 'id body_prefix module_id source_case datum', 'carrier selection')
    require(spec['carrier']['module_id'] == 'RNA' and spec['carrier']['source_case'] == 'stored' and spec['carrier']['datum'] == 'container_shell_bottom_front_center', 'Select exactly one closed RNA carrier and its explicit source datum')
    require(isinstance(spec['carrier']['id'], str) and spec['carrier']['id'], 'Carrier ID required')
    require(isinstance(spec['carrier']['body_prefix'], str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*_', spec['carrier']['body_prefix']), 'Stable native body prefix required')
    exact(spec['locations'], 'source handover', 'location roles')
    for role, location in spec['locations'].items():
        exact(location, 'id support_body top_frame static_case', 'location')
        require(all(isinstance(v, str) and v for v in location.values()), 'Named location fields required')
        require(location['static_case'] == ('shelf' if role == 'source' else 'handover'), 'Location role and static case differ')
    require(len({v['id'] for v in spec['locations'].values()}) == 2 and len({v['top_frame'] for v in spec['locations'].values()}) == 2 and len({v['support_body'] for v in spec['locations'].values()}) == 2, 'The source and handover places must remain distinct')
    exact(spec['nest'], 'id recipe host_location', 'fixed nest')
    identities = [spec['carrier']['id'], *[spec['carrier']['id']+'.Content%02d' % i for i in range(1, 10)], *[v['id'] for v in spec['locations'].values()], spec['nest']['id']]
    require(len(set(identities)) == len(identities), 'Carrier, symbolic content, place and fixture IDs must be distinct')
    require(spec['nest']['recipe'] == 'three_sided_fixed_low_guides_v1' and spec['nest']['host_location'] == spec['locations']['handover']['id'], 'Fixed nest must belong to the handover location')
    require(spec['cases'] == [{'id': 'shelf', 'location_role': 'source'}, {'id': 'handover', 'location_role': 'handover'}] and spec['display_case'] in {'shelf', 'handover'}, 'Two alternative static cases required')
    require(spec['measured_dimensions'] is None, 'Storage dimensions remain synthetic assumptions')
    exact(spec['qualification'], 'shelf_load_qualified nest_qualified grasp_qualified article_retention_verified lid_retention_verified stability_qualified trajectory_implemented hardware_executed inventory_implemented', 'qualification')
    require(all(v is False for v in spec['qualification'].values()), 'Storage is a synthetic unqualified fixture')
    p = parameters(spec)
    _scene(spec, p)
    return spec


def load(path=SOURCE):
    path = Path(path).resolve()
    require(path.is_relative_to((ROOT/'model').resolve()) and path.suffix == '.json', 'Storage source must be a local model JSON file')
    raw = path.read_bytes(); spec = json.loads(raw)
    validate(spec)
    sha = hashlib.sha256(raw).hexdigest()
    require(digest(path) == sha, 'Storage source changed while loading')
    spec['_source'] = {'path': str(path), 'sha256': sha}
    return spec


def cases(spec):
    return copy.deepcopy(spec['cases'])


def materialize(spec, case_id):
    require(case_id in {case['id'] for case in spec['cases']}, 'Unknown static storage case')
    result = copy.deepcopy(spec); result['display_case'] = case_id
    return result


def native_spec(spec, p):
    """Derived parameter closure for native expressions, never a leading file."""
    result = copy.deepcopy(spec)
    for name in DERIVED:
        result['parameters'][name] = {'expression': p[name], 'unit': 'mm', 'range': [p[name], p[name]],
                                     'description': 'Derived from the pinned K01 source; regenerate to change the carrier'}
    return result


def furnishings(spec, p):
    source = read(spec['sources']['furnishings'])
    exact(source, 'format id units parameters anchors expressions instances limitations', 'furnishings')
    require(source['format'] == 'solidcraftbot.furnishings/1' and source['units'] == spec['units'] and source['parameters'] == source['anchors'] == {}, 'Furniture definitions and scene parameters must not be duplicated')
    catalog = furniture.validate_catalog(read(spec['sources']['furniture']))
    require(len(source['instances']) == 2 and {i['id'] for i in source['instances']} == {v['support_body'] for v in spec['locations'].values()}, 'Exactly one shelf support and one handover support required')
    result = {'bodies': [], 'operations': [], 'frames': []}
    for instance in source['instances']:
        require(instance['type'] == 'reference_worktop' and instance['yaw_deg'] == 0 and instance['component'] == 'StorageFrame', 'Only translated reference support boxes are implemented')
        item = furniture.instantiate(catalog, instance, p, aliases=source['expressions'])
        require(not item['joints'] and len(item['bodies']) == len(item['operations']) == 1, 'Fixed primitive support required')
        for key in result:
            result[key].extend(item[key])
    frames = {frame['id'] for frame in result['frames']}
    require(len(frames) == 2 and frames == {v['top_frame'] for v in spec['locations'].values()}, 'Every location needs its declared top frame')
    return result


def _scene(spec, p):
    selected = selected_carrier(spec); placed = furnishings(spec, p)
    frame_by_id = {frame['id']: frame for frame in placed['frames']}
    boxes = {operation['body']: numeric_shape(operation['shape'], p) for operation in placed['operations']}
    locations = {}; expressions = {}
    for role, declaration in spec['locations'].items():
        frame = frame_by_id[declaration['top_frame']]
        origin = list(frame['origin']); origin[1] = '('+str(origin[1])+')-carrier_depth/2+(shelf_margin_front-shelf_margin_back)/2'
        seat = [evaluate(v, p) for v in origin]; shape = boxes[declaration['support_body']]
        bbox = {'min': shape['origin'], 'max': [a+b for a, b in zip(shape['origin'], shape['size'])]}
        require(abs(seat[2]-bbox['max'][2]) < 1e-9, 'Seat must coincide with its support top')
        footprint = {'min': [seat[0]-p['carrier_width']/2, seat[1], seat[2]], 'max': [seat[0]+p['carrier_width']/2, seat[1]+p['carrier_depth'], seat[2]]}
        require(all(bbox['min'][axis] <= footprint['min'][axis] and footprint['max'][axis] <= bbox['max'][axis] for axis in (0, 1)), 'Carrier footprint is not fully supported')
        locations[role] = {**copy.deepcopy(declaration), 'seat_origin_mm': seat, 'support_bbox_mm': bbox, 'footprint_bbox_mm': footprint}
        expressions[role] = origin
    a, b = (locations[role]['support_bbox_mm'] for role in ('source', 'handover'))
    require(any(a['max'][i] < b['min'][i] or b['max'][i] < a['min'][i] for i in (0, 1)), 'The two fixed places overlap')
    active = next(case['location_role'] for case in spec['cases'] if case['id'] == spec['display_case'])
    return selected, placed, locations, expressions, active


def _carrier_metadata(spec, selected):
    carrier_id = spec['carrier']['id']
    return {'id': carrier_id, 'instance_id': carrier_id, 'source': copy.deepcopy(spec['sources']['kit']),
            'module_id': spec['carrier']['module_id'], 'kit_id': selected['module']['kit_id'], 'source_case': spec['carrier']['source_case'], 'status': 'synthetic_unobserved',
            'symbolic_contents': [{'id': carrier_id+'.Content%02d' % (index+1), 'slot_id': item['slot_id'], 'material_id': item['material_id'],
                                   'roles': copy.deepcopy(item['roles']), 'status': 'symbolic_unobserved'} for index, item in enumerate(selected['module']['materials'])]}


def nest_geometry(handover):
    """The three local guides are defined once for construction and checks."""
    x, y, z = (str(v) for v in handover)
    operations = []
    for name, size, origin in [
        ('NestGuideLeft', ['nest_guide_t', 'carrier_depth', 'nest_guide_h'], [f'({x})-carrier_width/2-nest_clearance-nest_guide_t', y, z]),
        ('NestGuideRight', ['nest_guide_t', 'carrier_depth', 'nest_guide_h'], [f'({x})+carrier_width/2+nest_clearance', y, z]),
        ('NestGuideBack', ['carrier_width', 'nest_guide_t', 'nest_guide_h'], [f'({x})-carrier_width/2', f'({y})+carrier_depth+nest_clearance', z])]:
        operations.append({'id': name+'_Box', 'body': name, 'action': 'create', 'shape': {'kind': 'box', 'size': size, 'origin': origin}})
    return {'bodies': [{'id': op['body'], 'component': 'StorageFrame', 'role': 'fixed_unqualified_handover_guide', 'appearance': {'color': '#5b7d91', 'opacity': 1}} for op in operations], 'operations': operations}


def interfaces(spec, p):
    selected, placed, locations, expressions, active = _scene(spec, p)
    seat = locations[active]['seat_origin_mm']; delta = [a-b for a, b in zip(seat, selected['datum'])]
    prefix = spec['carrier']['body_prefix']; body_map = {prefix+body: body for body in selected['body_ids']}
    def translated(point):
        return [a+b for a, b in zip(point, delta)]
    frames = {}
    for identity, frame in selected['contract']['frames'].items():
        if frame['body'] not in selected['body_ids']:
            continue
        frames[prefix+identity] = {**copy.deepcopy(frame), 'id': prefix+identity, 'body': prefix+frame['body'], 'origin_mm': translated(frame['origin_mm']), 'source_frame_id': identity}
    probes = []
    for probe in selected['contract']['native_clearance_probes']:
        if prefix+probe['frame_id'] not in frames:
            continue
        probes.append({**copy.deepcopy(probe), 'id': prefix+probe['id'], 'frame_id': prefix+probe['frame_id'], 'origin_mm': translated(probe['origin_mm']), 'source_probe_id': probe['id']})
    support = locations[active]
    guides = {}
    for operation in nest_geometry(expressions['handover'])['operations']:
        shape = numeric_shape(operation['shape'], p)
        guides[operation['body']] = {'min': shape['origin'], 'max': [a+b for a, b in zip(shape['origin'], shape['size'])]}
    return {'carrier': _carrier_metadata(spec, selected), 'locations': locations, 'static_cases': [c['id'] for c in spec['cases']], 'active_location_id': support['id'],
            'source_body_map': body_map, 'source_datum_mm': selected['datum'], 'instance_translation_mm': delta,
            'frames': frames, 'native_clearance_probes': probes,
            'support': {'support_body': support['support_body'], 'body': support['support_body'], 'carrier_body': prefix+selected['interface']['container_body'],
                        'footprint_bbox_mm': support['footprint_bbox_mm'], 'contact_z_mm': seat[2], 'location_id': support['id'], 'qualification': 'synthetic_unqualified'},
            'nest': {'id': spec['nest']['id'], 'host_location_id': spec['nest']['host_location'], 'guide_bboxes_mm': guides, 'status': 'synthetic_unqualified'},
            'measured_dimensions': None, 'trajectory_implemented': False, 'inventory_implemented': False}


def expanded(spec, p):
    selected, placed, locations, expressions, active = _scene(spec, p)
    prefix = spec['carrier']['body_prefix']; identities = set(selected['body_ids'])
    components = {body['component'] for body in selected['source']['bodies'] if body['id'] in identities}
    result = {'id': spec['id'], 'status': spec['status'], 'parameters': native_spec(spec, p)['parameters'],
              'components': [{'id': 'StorageFrame', 'grounded': True}], 'bodies': copy.deepcopy(placed['bodies']), 'operations': copy.deepcopy(placed['operations']), 'joints': [], 'interfaces': interfaces(spec, p)}
    for component in selected['source']['components']:
        if component['id'] in components:
            require(not component.get('parent'), 'Only flat fixed K01 components are supported')
            result['components'].append({**copy.deepcopy(component), 'id': prefix+component['id']})
    for body in selected['source']['bodies']:
        if body['id'] in identities:
            result['bodies'].append({**copy.deepcopy(body), 'id': prefix+body['id'], 'component': prefix+body['component'], 'source_body_id': body['id']})
    for operation in selected['source']['operations']:
        if operation['body'] not in identities:
            continue
        shape = numeric_shape(operation['shape'], selected['p'])
        shape['origin'] = [f'({value-datum})+({origin})' for value, datum, origin in zip(shape['origin'], selected['datum'], expressions[active])]
        result['operations'].append({**copy.deepcopy(operation), 'id': prefix+operation['id'], 'body': prefix+operation['body'], 'shape': shape})
    nest = nest_geometry(expressions['handover'])
    result['bodies'].extend(nest['bodies']); result['operations'].extend(nest['operations'])
    require(len({body['id'] for body in result['bodies']}) == len(result['bodies']), 'Native body identities must be unique')
    return result


def pose(spec, p, name=None):
    require((name or spec['display_case']) == spec['display_case'], 'Materialize a separate static case; no motion channel exists')
    return {}


def validate_pose(source, values):
    require(source['joints'] == [] and values == {}, 'Storage has no joint or trajectory')


def samples(spec, p):
    return [{'id': spec['display_case'], 'values_mm': {}}]


def displacement(source, component, values):
    validate_pose(source, values)
    return [0, 0, 0]


def check_interface_geometry(spec, p, measurements):
    contract = interfaces(spec, p); selected = selected_carrier(spec)
    by_name = {row['body']: row for row in measurements}
    expected_source = {body: [] for body in selected['body_ids']}
    for operation in selected['source']['operations']:
        if operation['body'] in expected_source and operation['action'] in {'create', 'join'}:
            shape = numeric_shape(operation['shape'], selected['p']); low = shape['origin']
            if shape['kind'] == 'box':
                high = [a+b for a, b in zip(low, shape['size'])]
            else:
                x, y, z = low; r = shape['radius']; low = [x-r, y-r, z]; high = [x+r, y+r, z+shape['height']]
            expected_source[operation['body']].append({'min': low, 'max': high})
    delta = contract['instance_translation_mm']; checks = []
    def match(actual, expected):
        return max(abs(actual[edge][i]-expected[edge][i]) for edge in ('min', 'max') for i in range(3)) < 1e-7
    for body, source in contract['source_body_map'].items():
        require(body in by_name, 'Missing selected carrier body: '+body)
        boxes = expected_source[source]
        expected = {edge: [fn(box[edge][i] for box in boxes)+delta[i] for i in range(3)] for edge, fn in [('min', min), ('max', max)]}
        checks.append({'id': body+'_placement', 'passed': match(by_name[body]['bbox'], expected), 'source_body_id': source})
    for role, location in contract['locations'].items():
        require(location['support_body'] in by_name, 'Missing fixed support')
        checks.append({'id': role+'_support_placement', 'passed': match(by_name[location['support_body']]['bbox'], location['support_bbox_mm'])})
    for body, expected in contract['nest']['guide_bboxes_mm'].items():
        require(body in by_name, 'Missing fixed nest guide')
        checks.append({'id': body+'_placement', 'passed': match(by_name[body]['bbox'], expected)})
    return checks


def solidcraft_commands(spec, p):
    commands = portable.solidcraft_commands(native_spec(spec, p), p, provider=sys.modules[__name__])
    for command in commands:
        if command['command'] == 'document.metadata.set':
            old = command['params']['values'].pop('org.solidcraftbot.tube-carrier')
            command['params']['values']['org.solidcraftbot.synthetic-kit-storage'] = {**old, 'case': spec['display_case'], 'carrier': interfaces(spec, p)['carrier'], 'trajectory_implemented': False}
    return commands


def source_dependencies(spec):
    origin = Path(spec.get('_source', {}).get('path', SOURCE))
    paths = [origin, SCHEMA, Path(__file__), ROOT/'scripts/furniture_model.py', ROOT/'model/furniture-catalog.schema.json', ROOT/'model/furnishings.schema.json', ROOT/'model/room-geometry.schema.json']
    paths += [ROOT/ref['source'] for ref in spec['sources'].values()]
    paths += kit.source_dependencies(selected_carrier(spec)['spec'])
    return list(dict.fromkeys(Path(path).resolve() for path in paths))


def runtime_definition(spec=None):
    spec = load() if spec is None else spec
    origin = spec.get('_source')
    require(isinstance(origin, dict) and set(origin) == {'path', 'sha256'}, 'Load a byte-bound storage source before runtime projection')
    raw = Path(origin['path']).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == origin['sha256'], 'Loaded storage source changed before runtime projection')
    current = json.loads(raw)
    effective = {key: copy.deepcopy(value) for key, value in spec.items() if key != '_source'}
    effective['display_case'] = current['display_case']  # A static view does not alter the runtime identities.
    require(effective == current, 'Runtime projection requires the unchanged loaded source')
    paths = source_dependencies(spec); pins = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    require(pins[str(Path(origin['path']).relative_to(ROOT))] == origin['sha256'], 'Loaded storage source changed before runtime projection')
    contract = interfaces(spec, parameters(spec))
    result = {'fixture_id': spec['id'], 'carrier': contract['carrier'],
              'locations': {role: {k: value[k] for k in ('id', 'static_case', 'support_body')} for role, value in contract['locations'].items()},
              'route': [contract['locations'][role]['id'] for role in ('source', 'handover', 'source')], 'source_files_sha256': pins}
    require(all(digest(ROOT/path) == sha for path, sha in pins.items()), 'Storage dependency changed during runtime projection')
    return result
