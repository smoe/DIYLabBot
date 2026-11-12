"""Four static concept storeys from one relative floorplan, never a survey.

XY is presentation-scaled using an unmeasured room parameter. Z uses explicit
owner/presentation assumptions. The exchange marker is semantic geometry only.
"""
from pathlib import Path
import copy
import hashlib
import json
import math
import re

import assembly_model as assembly
import building_circulation as circulation
import building_roof as roof
import ground_floor_model as ground
import relative_floorplan as floor
import robot_spec as robot
import room_geometry_model as room
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/building-stack.shared.json'
SCHEMA = ROOT/'model/building-stack.schema.json'
FORMAT = 'solidcraftbot.building-stack/1'
DRIVING = ('clear_height_mm', 'slab_thickness_mm')
digest = robot.digest
evaluate = robot.evaluate
numeric_shape = floor.numeric_shape


def require(condition, message):
    if not condition: raise ValueError(message)


def exact(value, fields, name):
    require(isinstance(value, dict) and set(value) == set(fields.split()), 'Invalid '+name+' fields')


def _spec(spec): return spec.get('_stack', spec)


def read(ref):
    exact(ref, 'source source_sha256', 'pinned reference')
    path = assembly.validate_reference(ref, root=ROOT); raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref['source_sha256'], 'Source changed while reading')
    return json.loads(raw)


def templates(spec):
    spec = _spec(spec)
    read(spec['sources']['floorplan'])
    plan = floor.load(assembly.validate_reference(spec['sources']['floorplan'], root=ROOT))
    require(plan['_source']['sha256'] == spec['sources']['floorplan']['source_sha256'], 'Canonical floorplan changed while loading')
    reference = read(spec['sources']['room_geometry'])
    require(reference.get('format') == 'solidcraftbot.room-geometry/1' and reference.get('units') == {'length': 'mm', 'angle': 'deg'}, 'Typed reference room geometry required')
    return plan, reference


def parameters(spec, overrides=None):
    raw = _spec(spec)
    require(not set(overrides or {})-set(DRIVING), 'Only height and slab assumptions may be overridden')
    values = {name: spec['parameters'][name]['expression'] for name in DRIVING} if '_stack' in spec else {}
    values.update(overrides or {})
    p = robot.parameters(raw, values)
    require(set(raw['parameters']) == set(DRIVING), 'Only independent vertical assumptions belong to the stack source')
    for name in DRIVING:
        definition = raw['parameters'][name]
        exact(definition, 'expression unit range basis description', 'vertical assumption')
        bounds = definition['range']
        require(definition['unit'] == 'mm' and len(bounds) == 2 and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in bounds) and bounds[0] <= bounds[1], 'Positive finite mm bounds required')
        require(bounds[0] <= p[name] <= bounds[1], 'Vertical assumption outside declared range')
        require(definition['basis'] == ('owner_assumption' if name == 'clear_height_mm' else 'presentation_assumption'), 'Declare the basis of each vertical assumption')
    plan, reference = templates(raw); ref = raw['presentation_reference']; rp = room.parameters(reference)
    selected = next((a for a in plan['areas'] if a['id'] == ref['floorplan_area']), None)
    require(selected is not None and selected['kind'] == 'room', 'Existing room area required for presentation proportion')
    polygon = floor.outline(plan, selected); extent = max(x for x, y in polygon)-min(x for x, y in polygon)
    require(extent > 0, 'Reference area has no X extent')
    for key in ('width_parameter', 'wall_thickness_parameter', 'door_height_parameter'):
        name = ref[key]
        require(name in rp and reference['parameters'][name]['unit'] == 'mm' and rp[name] > 0, 'Positive mm source parameter required')
    p.update({'display_scale': rp[ref['width_parameter']]/extent, 'display_height': p['clear_height_mm'],
              'display_thickness': rp[ref['wall_thickness_parameter']], 'display_floor_depth': p['slab_thickness_mm'],
              'door_height_mm': rp[ref['door_height_parameter']], 'reference_width_mm': rp[ref['width_parameter']],
              'floor_pitch_mm': p['clear_height_mm']+p['slab_thickness_mm']})
    require(0 < p['door_height_mm'] < p['clear_height_mm'], 'Presentation door must leave a lintel under the assumed clear height')
    return p


def validate(spec):
    spec = _spec(spec); leading = {k: v for k, v in spec.items() if k != '_source'}
    exact(leading, 'format id sources calibration parameters presentation_reference levels atrium concept_exchange circulation roof qualification limitations', 'building stack')
    require(spec['format'] == FORMAT and spec['calibration'] is None, 'Uncalibrated building concept required')
    require(isinstance(spec['id'], str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', spec['id']), 'Stable stack ID required')
    exact(spec['sources'], 'floorplan room_geometry ground_floor', 'stack sources')
    ref = spec['presentation_reference']
    exact(ref, 'width_parameter wall_thickness_parameter door_height_parameter floorplan_area extent_axis basis', 'presentation reference')
    require(ref['extent_axis'] == 'x' and ref['basis'] == 'unmeasured_concept_proportion', 'Presentation proportion is not metric calibration')
    require([level['id'] for level in spec['levels']] == ['EG', 'OG1', 'OG2', 'OG3'], 'Exactly four ordered concept storeys required; basement remains unimplemented')
    for level in spec['levels']:
        exact(level, 'id label', 'level instance')
        require(isinstance(level['label'], str) and level['label'], 'Level label required')
    exact(spec['atrium'], 'area floor_levels', 'atrium override')
    require(spec['atrium']['floor_levels'] == ['EG'], 'Only the ground-storey atrium receives a floor')
    marker = spec['concept_exchange']
    exact(marker, 'id footprint_fraction color opacity status', 'semantic marker')
    require(marker['id'] == 'ConceptExchange' and marker['status'] == 'semantic_visualization_only', 'Marker is not hardware or a transport model')
    require(type(marker['footprint_fraction']) in (int, float) and math.isfinite(marker['footprint_fraction']) and 0 < marker['footprint_fraction'] < 1, 'Interior marker fraction required')
    require(type(marker['opacity']) in (int, float) and math.isfinite(marker['opacity']) and 0 < marker['opacity'] < 1 and re.fullmatch('#[0-9a-fA-F]{6}', marker['color']), 'Transparent semantic marker required')
    exact(spec['qualification'], 'metric_scale_known surveyed_heights structural_qualified transport_implemented trajectory_implemented hardware_executed fire_safety_qualified', 'qualification')
    require(all(value is False for value in spec['qualification'].values()), 'Concept assumptions do not qualify a real building or transport system')
    require(isinstance(spec['limitations'], list) and spec['limitations'] and all(isinstance(text, str) and text for text in spec['limitations']), 'Explicit text limitations required')
    p = parameters(spec); plan, reference = templates(spec)
    atrium_polygon(spec, plan)
    marker_polygon(spec, atrium_polygon(spec, plan))
    circulation.validate_source(spec['circulation'])
    interfaces(spec, p)
    return spec


def load(path=SOURCE):
    path = Path(path).resolve(); raw = path.read_bytes(); spec = json.loads(raw)
    validate(spec); sha = hashlib.sha256(raw).hexdigest()
    require(digest(path) == sha, 'Stack source changed while loading')
    spec['_source'] = {'path': str(path), 'sha256': sha}
    return spec


def atrium_polygon(spec, plan):
    area = next((a for a in plan['areas'] if a['id'] == spec['atrium']['area']), None)
    require(area is not None and area['kind'] == 'void', 'Existing source void area required')
    return floor.outline(plan, area)


def marker_polygon(spec, polygon):
    low = [min(p[i] for p in polygon) for i in (0, 1)]; high = [max(p[i] for p in polygon) for i in (0, 1)]
    half = [(high[i]-low[i])*spec['concept_exchange']['footprint_fraction']/2 for i in (0, 1)]
    center = [(a+b)/2 for a, b in zip(low, high)]
    def rectangle(point):
        x, y = point; w, h = half
        return [[x-w, y-h], [x+w, y-h], [x+w, y+h], [x-w, y+h]]
    def safe(points):
        if any(floor.point_membership(p, polygon) != 1 for p in points): return False
        for a, b in zip(points, points[1:]+points[:1]):
            for c, d in zip(polygon, polygon[1:]+polygon[:1]):
                if floor.side(a, b, c)*floor.side(a, b, d) == -1 and floor.side(c, d, a)*floor.side(c, d, b) == -1: return False
        return True
    candidates = [center]+sorted([[low[0]+(i+.5)*(high[0]-low[0])/21, low[1]+(j+.5)*(high[1]-low[1])/21] for j in range(21) for i in range(21)], key=lambda point: math.dist(point, center))
    result = next((rectangle(point) for point in candidates if safe(rectangle(point))), None)
    require(result is not None, 'Declared marker rectangle does not fit strictly inside the source atrium')
    return result


def level_plan(spec, level_id):
    """Resolve the actual registered EG once; upper floors reuse canonical F03."""
    raw = _spec(spec)
    if level_id == 'EG':
        ref = raw['sources']['ground_floor']; read(ref)
        plan = ground.load(assembly.validate_reference(ref, root=ROOT))
        require(plan['_source']['sha256'] == ref['source_sha256'], 'EG source changed while loading')
        require(ground.raw_source(plan)['reference_floorplan'] == raw['sources']['floorplan'], 'EG registration must reference the same pinned canonical F03')
        return plan
    require(level_id in {'OG1', 'OG2', 'OG3'}, 'Unknown building level')
    return templates(raw)[0]


def _bases(spec, p):
    display = {k: p[k] for k in ('display_scale', 'display_height', 'display_thickness', 'display_floor_depth')}
    result = {}
    for level in spec['levels']:
        plan = level_plan(spec, level['id'])
        base = floor.expanded(plan, display); original = floor.interfaces(plan, display)
        # Only the stack projection changes: the public F03 trace stays intact.
        ext_area = spec['circulation']['external_stair']['area']
        incident = {}
        for area in plan['areas']:
            for ref in area['boundary']: incident.setdefault(ref['wall'], set()).add(area['id'])
        omitted = {'Area_'+ext_area} | {'Wall_'+name for name, uses in incident.items() if uses == {ext_area}}
        base['bodies'] = [body for body in base['bodies'] if body['id'] not in omitted]
        base['operations'] = [op for op in base['operations'] if op['body'] not in omitted]
        original['opening_probes'] = [probe for probe in original['opening_probes'] if probe['target_body'] not in omitted]
        result[level['id']] = (plan, base, original)
    return result


def interfaces(spec, p):
    spec = _spec(spec); plan, _ = templates(spec); bases = _bases(spec, p)
    polygon = [[x*p['display_scale'], y*p['display_scale']] for x, y in atrium_polygon(spec, plan)]
    marker = [[x*p['display_scale'], y*p['display_scale']] for x, y in marker_polygon(spec, atrium_polygon(spec, plan))]
    levels = []; probes = []; voids = []; vertices = []
    for index, level in enumerate(spec['levels']):
        chosen, base, originals = bases[level['id']]
        vertices.extend(chosen['vertices'].values())
        prefix = level['id']+'__'; z = index*p['floor_pitch_mm']; filled = level['id'] in spec['atrium']['floor_levels']
        walls = [b['id'] for b in base['bodies'] if b['role'] == 'relative_wall_display']
        slabs = [b['id'] for b in base['bodies'] if b['role'] == 'relative_area_display']
        floor_ids = [prefix+name for name in slabs]
        levels.append({**level, 'index': index, 'z_mm': z, 'slab_bottom_mm': z-p['slab_thickness_mm'], 'slab_top_mm': z, 'clear_top_mm': z+p['clear_height_mm'],
                       'template_source': spec['sources']['ground_floor' if level['id'] == 'EG' else 'floorplan']['source'], 'template_id': chosen['id'],
                       'atrium_floor_filled': filled, 'wall_bodies': [prefix+name for name in walls], 'floor_bodies': floor_ids})
        if not filled:
            voids.append({'id': level['id']+'_AtriumVoid', 'kind': 'polygon_prism', 'points_mm': polygon, 'offset_mm': z-p['slab_thickness_mm'], 'depth_mm': p['slab_thickness_mm'], 'target_bodies': floor_ids})
        opening_by_id = {opening['id']: opening for opening in chosen['openings']}
        for probe in originals['opening_probes']:
            value = {**copy.deepcopy(probe), 'id': prefix+probe['id'], 'target_body': prefix+probe['target_body'], 'offset_mm': z+probe['offset_mm']}
            if opening_by_id[probe['id']]['kind'] == 'door': value['depth_mm'] = p['door_height_mm']-2*probe['display_inset_mm']
            require(value['depth_mm'] > 0, 'Presentation door cannot contain its inherited opening probe')
            probes.append(value)
    ground_probe = {'id': 'EG_AtriumCoverage', 'target_bodies': list(levels[0]['floor_bodies']), 'expectation': 'union_filled', 'kind': 'polygon_prism', 'points_mm': polygon, 'offset_mm': -p['slab_thickness_mm'], 'depth_mm': p['slab_thickness_mm'], 'expected_volume_mm3': floor.signed_area(polygon)*p['slab_thickness_mm']}
    concept = {'body': spec['concept_exchange']['id'], 'points_mm': marker, 'offset_mm': 0, 'depth_mm': levels[-1]['clear_top_mm'], 'status': 'semantic_visualization_only'}
    data = {'levels': levels, 'clear_height_mm': p['clear_height_mm'], 'slab_thickness_mm': p['slab_thickness_mm'], 'floor_pitch_mm': p['floor_pitch_mm'],
            'ground_floor': {'id': bases['EG'][0]['id'], 'source': spec['sources']['ground_floor']['source']},
            'template_source': spec['sources']['floorplan']['source'], 'template_id': plan['id'], 'x_bounds_mm': [min(v[0] for v in vertices)*p['display_scale'], max(v[0] for v in vertices)*p['display_scale']],
            'y_bounds_mm': [min(v[1] for v in vertices)*p['display_scale'], max(v[1] for v in vertices)*p['display_scale']],
            'atrium_x_bounds_mm': [min(v[0] for v in polygon), max(v[0] for v in polygon)], 'atrium_polygon_mm': polygon,
            'atrium_y_bounds_mm': [min(v[1] for v in polygon), max(v[1] for v in polygon)],
            'opening_probes': probes, 'atrium_prisms': voids, 'ground_fill_probe': ground_probe, 'concept_marker': concept,
            'marker_body_ids': [concept['body']], 'wall_visibility_ids': [name for level in levels for name in level['wall_bodies']],
            'assumed_dimensions': copy.deepcopy(p), 'coordinate_meaning': {'xy': 'presentation_mm', 'z': 'assumed_mm'}, 'metric_scale_known': False,
            'structural_qualified': False, 'transport_implemented': False, 'trajectory_implemented': False, 'hardware_executed': False, 'fire_safety_qualified': False,
            'room_label_policy': 'EG uses the owner-labelled registered ground-floor source; OG labels are level-scoped F03 template references', 'limitations': list(spec['limitations'])}
    extra = circulation.compile(spec['circulation'], plan, p, levels, ground_plan=bases['EG'][0])
    data['circulation'] = extra['interface']
    data['external_area_overlay'] = {'area': spec['circulation']['external_stair']['area'], 'full_slabs_omitted': True,
        'exclusive_boundary_walls_omitted': True, 'shared_facade_walls_preserved': True, 'source_unchanged': True}
    data['wall_visibility_ids'].extend(extra['interface']['wall_bridge_ids'])
    data['roof'] = roof.compile(spec['roof'], plan, p, levels)['interface']
    return data


def native_spec(spec, p):
    return {'id': _spec(spec)['id'], 'status': 'Concept building stack; XY presentation proportions and assumed Z, not measured building geometry',
            'parameters': {name: {'expression': value, 'unit': 'mm', 'range': [value, value], 'description': 'Unmeasured concept/presentation dimension; not building calibration'} for name, value in p.items()}, '_stack': _spec(spec)}


def expanded(spec, p):
    spec = _spec(spec); plan, _ = templates(spec); bases = _bases(spec, p); data = interfaces(spec, p)
    result = {'id': spec['id'], 'status': 'Static concept visualization only', 'parameters': native_spec(spec, p)['parameters'], 'components': [], 'bodies': [], 'operations': [], 'joints': []}
    for level in data['levels']:
        chosen, base, _ = bases[level['id']]
        doors = {'Opening_'+o['id'] for o in chosen['openings'] if o['kind'] == 'door'}
        prefix = level['id']+'__'; component = level['id']+'_Layer'
        result['components'].append({'id': component, 'grounded': True})
        for body in base['bodies']:
            role = 'concept_storey_wall' if body['role'] == 'relative_wall_display' else 'concept_storey_slab'
            result['bodies'].append({**copy.deepcopy(body), 'id': prefix+body['id'], 'component': component, 'role': role, 'source_body_id': body['id'], 'level_id': level['id']})
        for operation in base['operations']:
            shape = numeric_shape(operation['shape'], p)
            if operation['id'] in doors: shape['depth'] = p['door_height_mm']
            shape['offset'] += level['z_mm']
            result['operations'].append({**copy.deepcopy(operation), 'id': prefix+operation['id'], 'body': prefix+operation['body'], 'shape': shape})
    def prism(name, component, role, points, offset, depth, color, opacity=1):
        result['bodies'].append({'id': name, 'component': component, 'role': role, 'appearance': {'color': color, 'opacity': opacity}})
        result['operations'].append({'id': name+'_Profile', 'body': name, 'action': 'create', 'shape': {'kind': 'polygon_prism', 'plane': 'XY', 'points': points, 'offset': offset, 'depth': depth, 'fixed': True}})
    result['components'].append({'id': 'ConceptMarker', 'grounded': True}); marker = data['concept_marker']
    prism(marker['body'], 'ConceptMarker', 'semantic_exchange_marker', marker['points_mm'], marker['offset_mm'], marker['depth_mm'], spec['concept_exchange']['color'], spec['concept_exchange']['opacity'])
    extra = circulation.compile(spec['circulation'], plan, p, data['levels'], ground_plan=bases['EG'][0])
    roof_geometry = roof.compile(spec['roof'], plan, p, data['levels'])
    for key in ('components', 'bodies', 'operations'):
        result[key].extend(extra[key]); result[key].extend(roof_geometry[key])
    return result


def cases(spec): return [{'id': 'stacked'}]
def materialize(spec, case_id):
    require(case_id == 'stacked', 'Only the static four-storey stack is implemented'); return copy.deepcopy(spec)
def pose(spec, p, name=None):
    require(name in (None, 'stacked'), 'No building or transport motion is implemented'); return {}
def validate_pose(source, values):
    require(source['joints'] == [] and values == {}, 'Stack has no motion channels')
def samples(spec, p): return [{'id': 'stacked', 'values_mm': {}}]
def displacement(source, component, values):
    validate_pose(source, values); return [0, 0, 0]


def solidcraft_commands(spec, p):
    raw = _spec(spec)
    class Provider:
        SOURCE = Path(raw.get('_source', {}).get('path', __file__))
        expanded = staticmethod(expanded)
        pose = staticmethod(pose)
        samples = staticmethod(samples)
    commands = portable.solidcraft_commands(native_spec(raw, p), p, provider=Provider)
    for command in commands:
        if command['command'] == 'document.metadata.set':
            command['params']['values'] = {'org.solidcraftbot.building-stack': {'source_id': raw['id'], 'metric_scale_known': False, 'coordinate_meaning': {'xy': 'presentation_mm', 'z': 'assumed_mm'}, 'transport_implemented': False}}
    return commands


def source_dependencies(spec):
    spec = _spec(spec); plan, reference = templates(spec)
    paths = [SCHEMA, Path(__file__), ROOT/'scripts/building_circulation.py', ROOT/'scripts/building_roof.py', *ground.source_dependencies(level_plan(spec, 'EG')), ROOT/'scripts/assembly_model.py', ROOT/'model/assembly-reference.schema.json', ROOT/'scripts/room_geometry_model.py', ROOT/spec['sources']['room_geometry']['source'], *floor.source_dependencies(plan)]
    if '_source' in spec: paths.insert(0, Path(spec['_source']['path']))
    return list(dict.fromkeys(paths))
