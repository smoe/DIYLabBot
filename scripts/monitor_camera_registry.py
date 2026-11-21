"""Derive a read-only model-view registry from the bound building inventory.

The outer composition references the walkthrough and fleet, never vice versa.
Fleet entries are metadata only: this module receives no vehicle poses, images,
telemetry, control ports, or authoritative fleet state.
"""
import hashlib
import json
import math
from pathlib import Path
import re

import assembly_model as assembly
import lab_layout_model as layout
import robot_cameras
import robot_components
import robot_spec as robot

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/foyer-camera-wall.shared.json'
SCHEMA = ROOT / 'model/foyer-camera-wall.schema.json'
FORMAT = 'solidcraftbot.foyer-camera-wall/1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate camera-wall field: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite camera-wall value')))


def exact(value, fields, where):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError('Unexpected ' + where + ' fields')


def finite(value, lower, upper, where):
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError('Invalid ' + where)


def validate_shape(value, schema, definitions=None, where='$'):
    """Evaluate this small, closed schema vocabulary without optional packages."""
    allowed = {'$schema', '$defs', '$ref', 'title', 'description', 'type', 'properties',
               'required', 'additionalProperties', 'items', 'minItems', 'maxItems',
               'minimum', 'maximum', 'minLength', 'minProperties', 'propertyNames',
               'pattern', 'const', 'enum'}
    if not isinstance(schema, dict) or set(schema) - allowed:
        raise ValueError('Unsupported camera-wall schema keyword at ' + where)
    definitions = schema.get('$defs', {}) if definitions is None else definitions
    if '$ref' in schema:
        reference = schema['$ref']
        if not isinstance(reference, str) or not reference.startswith('#/$defs/') or reference[8:] not in definitions:
            raise ValueError('Unsupported camera-wall schema reference at ' + where)
        validate_shape(value, definitions[reference[8:]], definitions, where)
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise ValueError('Unexpected constant at ' + where)
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        raise ValueError('Unexpected choice at ' + where)
    kind = schema.get('type')
    checks = {'object': lambda: type(value) is dict, 'array': lambda: type(value) is list,
              'string': lambda: type(value) is str, 'integer': lambda: type(value) is int,
              'number': lambda: type(value) in (int, float) and math.isfinite(value)}
    if kind is not None and (kind not in checks or not checks[kind]()):
        raise ValueError('Invalid camera-wall schema type at ' + where)
    if kind == 'object':
        properties = schema.get('properties', {})
        if not set(schema.get('required', [])) <= set(value) or len(value) < schema.get('minProperties', 0):
            raise ValueError('Missing camera-wall schema field at ' + where)
        for key, item in value.items():
            if 'propertyNames' in schema:
                validate_shape(key, schema['propertyNames'], definitions, where + '.<key>')
            rule = properties.get(key, schema.get('additionalProperties', True))
            if rule is False:
                raise ValueError('Unexpected camera-wall field at ' + where + '.' + key)
            if isinstance(rule, dict):
                validate_shape(item, rule, definitions, where + '.' + key)
            elif rule is not True:
                raise ValueError('Unsupported camera-wall object schema at ' + where)
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', math.inf):
            raise ValueError('Invalid camera-wall array length at ' + where)
        for index, item in enumerate(value):
            validate_shape(item, schema['items'], definitions, where + '[' + str(index) + ']')
    elif kind == 'string' or 'pattern' in schema:
        if not isinstance(value, str) or len(value) < schema.get('minLength', 0) or ('pattern' in schema and re.search(schema['pattern'], value) is None):
            raise ValueError('Invalid camera-wall string at ' + where)
    elif kind in ('integer', 'number'):
        if not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):
            raise ValueError('Camera-wall value outside schema bounds at ' + where)


def load(source=SOURCE):
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    spec = read_json(path)
    validate_shape(spec, read_json(SCHEMA))
    exact(spec, 'format id sources settings asset_policy basic_laboratory_hoods microscopy', 'camera-wall')
    if spec['format'] != FORMAT or spec['id'] != 'FoyerCameraWall':
        raise ValueError('Unknown camera-wall composition')
    exact(spec['sources'], 'walkthrough fleet', 'camera-wall sources')
    for ref in spec['sources'].values():
        exact(ref, 'source source_sha256', 'camera-wall reference')
        assembly.validate_reference(ref, root=ROOT)
    settings = spec['settings']
    exact(settings, 'resolution_px mosaic_rate_hz selected_rate_hz virtual_fov_y_deg near_mm modeled_far_mm virtual_near_mm far_mm stale_after_s history_enabled', 'camera-wall settings')
    resolution = settings['resolution_px']
    if not isinstance(resolution, list) or len(resolution) != 2 or any(type(v) is not int or not 16 <= v <= 1920 for v in resolution):
        raise ValueError('Bounded integer camera resolution required')
    for key in ('mosaic_rate_hz', 'selected_rate_hz'):
        finite(settings[key], .1, 30, key)
    if settings['selected_rate_hz'] < settings['mosaic_rate_hz']:
        raise ValueError('Selected view cannot update slower than the mosaic')
    finite(settings['virtual_fov_y_deg'], 1, 150, 'virtual field of view')
    # These explicit clipping assumptions preserve depth precision. They are
    # neither camera sensor ranges nor the illustrative source-cone length.
    finite(settings['near_mm'], .01, 100, 'modeled-camera near clipping plane')
    finite(settings['modeled_far_mm'], settings['near_mm'] + 1, 1000000, 'modeled-camera far clipping plane')
    finite(settings['virtual_near_mm'], .01, 100, 'virtual-overview near clipping plane')
    finite(settings['far_mm'], settings['virtual_near_mm'] + 1, 1000000, 'virtual-overview far clipping plane')
    finite(settings['stale_after_s'], 1, 120, 'stale threshold')
    if settings['history_enabled'] is not False:
        raise ValueError('Camera-wall history is not implemented')
    if spec['basic_laboratory_hoods'] is not True or spec['microscopy'] is not True:
        raise ValueError('Bound laboratory hoods and microscopy belong to the registry')
    if not isinstance(spec['asset_policy'], dict) or not spec['asset_policy']:
        raise ValueError('Asset-type inclusion policy required')
    for asset, rule in spec['asset_policy'].items():
        exact(rule, 'mode label', 'camera asset policy')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', asset) or rule['mode'] not in {'arm_cameras', 'overview', 'no_camera', 'exclude'}:
            raise ValueError('Unknown asset inclusion rule')
        if not isinstance(rule['label'], str) or not rule['label']:
            raise ValueError('Public camera asset label required')
    return path, spec


def _vector(matrix, vector):
    return [sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3)]


def arm_cameras(laboratory, device, item, equipment, settings):
    """Compose model-zero optical frames with instance FK and world placement."""
    spec = layout.instance_source(equipment, item)
    fk = robot.forward(spec, item['joints_deg'])
    result = []
    aspect = settings['resolution_px'][0] / settings['resolution_px'][1]
    for camera in robot_cameras.audit(spec)['cameras']:
        frame = camera['optical_frame']
        _, down, forward = robot_components.axes(frame)
        mount = robot.multiply(device['world_pose'], fk[camera['mounted_link']])
        eye = robot.transform(mount, frame['origin_mm'])
        direction = _vector(mount, forward)
        up = [-v for v in _vector(mount, down)]
        purpose = 'Greiferkamera' if camera['purpose'] == 'tip' else 'Übersichtskamera'
        result.append({
            'id': laboratory['id'] + '.' + device['id'] + '.' + camera['id'],
            'device_id': laboratory['id'] + '.' + device['id'],
            'label': device['id'] + ' · ' + purpose,
            'location': laboratory.get('room', laboratory['id']),
            'level_id': laboratory['level_id'], 'category': 'robot',
            'kind': 'modeled_camera', 'availability': 'available',
            'physical_camera': False,
            'origin_label': 'Modellkamera / synthetisches Livebild',
            'reason': None, 'eye_mm': eye,
            'target_mm': [a + b * camera['cone_range_mm'] for a, b in zip(eye, direction)],
            'up': up,
            'fov_y_deg': math.degrees(2 * math.atan(camera['cone_far_radius_mm'] / camera['cone_range_mm'] / math.sqrt(1 + aspect * aspect))),
            'near_mm': settings['near_mm'], 'far_mm': settings['modeled_far_mm'],
            'clipping_basis': 'presentation_assumption_not_optical_range',
            'mount_body_id': device['body_prefix'] + camera['id'] + '_body_ENVELOPE',
            'mounted_link': camera['mounted_link'], 'reference_joints_deg': list(item['joints_deg']),
            'calibrated': False, 'hardware_executed': False,
        })
    return result


def _overview(identity, label, laboratory, viewpoint, settings, category='device'):
    camera = {'id': identity + '.Overview', 'device_id': identity, 'label': label,
              'location': laboratory.get('room', laboratory.get('id', '')),
              'level_id': laboratory['level_id'], 'category': category,
              'kind': 'virtual_overview', 'physical_camera': False,
              'origin_label': 'Virtuelle Übersicht – keine physische Kamera',
              'availability': 'available' if viewpoint else 'missing_viewpoint',
              'reason': None if viewpoint else 'Kein quellgebundener Blickpunkt vorhanden',
              'mount_body_id': None, 'up': [0, 0, 1],
              'fov_y_deg': settings['virtual_fov_y_deg'],
              'near_mm': settings['virtual_near_mm'], 'far_mm': settings['far_mm'],
              'clipping_basis': 'presentation_assumption_not_optical_range',
              'eye_mm': None, 'target_mm': None,
              'calibrated': False, 'hardware_executed': False}
    if viewpoint:
        for key in ('eye_mm', 'target_mm'):
            values = viewpoint[key]
            if not isinstance(values, list) or len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError('Finite source-derived camera viewpoint required')
            camera[key] = list(values)
        if math.dist(camera['eye_mm'], camera['target_mm']) < 1:
            raise ValueError('Overview eye and target must differ')
    return camera


def _viewpoint(objects, identity):
    candidates = [obj for obj in objects if obj['id'].startswith(identity + '.') and obj.get('viewpoint')]
    return min(candidates, key=lambda obj: obj['id'])['viewpoint'] if candidates else None


def compile(program, interface, source=SOURCE):
    """Return derived views; no state, camera frame, or inventory is persisted."""
    path, spec = load(source)
    settings = spec['settings']
    walkthrough_ref = spec['sources']['walkthrough']
    if program.get('source_files_sha256', {}).get(walkthrough_ref['source']) != walkthrough_ref['source_sha256']:
        raise ValueError('Camera wall and walkthrough use different source revisions')
    pins = {str(path.resolve().relative_to(ROOT)): digest(path),
            str(SCHEMA.relative_to(ROOT)): digest(SCHEMA),
            str(Path(__file__).resolve().relative_to(ROOT)): digest(__file__)}
    pins.update({ref['source']: ref['source_sha256'] for ref in spec['sources'].values()})
    for module in (robot_cameras, robot_components, robot, layout):
        pins[str(Path(module.__file__).resolve().relative_to(ROOT))] = digest(module.__file__)
    objects = program.get('objects', [])
    cameras = []
    gaps = []
    for laboratory in interface.get('laboratories', []):
        equipment = None
        definitions = {}
        if laboratory.get('layout_source'):
            equipment_path = assembly.validate_reference(laboratory['layout_source'], root=ROOT)
            equipment = read_json(equipment_path)
            definitions = {item['id']: item for item in equipment['instances']}
            pins[str(equipment_path.relative_to(ROOT))] = digest(equipment_path)
        for device in laboratory.get('device_instances', []):
            identity = laboratory['id'] + '.' + device['id']
            rule = spec['asset_policy'].get(device['asset'])
            if rule is None:
                gaps.append({'device_id': identity, 'reason': 'unclassified_asset', 'asset': device['asset']})
                continue
            mode = rule['mode']
            if mode == 'exclude':
                continue
            if mode == 'arm_cameras':
                if not equipment or device['id'] not in definitions:
                    raise ValueError('Bound arm layout instance required')
                cameras.extend(arm_cameras(laboratory, device, definitions[device['id']], equipment, settings))
            else:
                camera = _overview(identity, rule['label'] + ' · ' + device['id'], laboratory,
                                   _viewpoint(objects, identity), settings,
                                   'transporter' if device['asset'] == 'transporter' else 'device')
                if mode == 'no_camera':
                    camera.update(availability='no_camera', reason='An dieser Instanz keine Kamera modelliert',
                                  eye_mm=None, target_mm=None)
                cameras.append(camera)
        for item in laboratory.get('instances', []):
            if item.get('layout_kind') != 'hood':
                continue
            identity = laboratory['id'] + '.' + item['id']
            cameras.append(_overview(identity, 'Abzug · ' + laboratory.get('room', laboratory['id']),
                                     laboratory, _viewpoint(objects, identity), settings))
    microscopy = interface.get('microscopy')
    if microscopy:
        viewpoint = next((stop for stop in program.get('stops', [])
                          if stop.get('anchor', {}).get('kind') == 'microscopy'
                          and stop['anchor'].get('station') == microscopy['id']), None)
        cameras.append(_overview(microscopy['id'], 'Mikroskop · 3.007',
                                 {'id': microscopy['id'], 'room': '3.007', 'level_id': microscopy['level_id']},
                                 viewpoint, settings))
    fleet_path = assembly.validate_reference(spec['sources']['fleet'], root=ROOT)
    fleet = read_json(fleet_path)
    if fleet.get('format') != 'solidcraftbot.building-fleet-demo/1':
        raise ValueError('Known fleet definition required for disconnected metadata')
    pattern = fleet.get('fleet', {}).get('id_pattern', '')
    match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*)\{([0-9]+)\.\.([0-9]+)\}', pattern)
    count = fleet.get('fleet', {}).get('count')
    if not match or type(count) is not int or not 1 <= count <= 128:
        raise ValueError('Bounded source-derived fleet identifiers required')
    prefix, start, end = match.groups()
    if len(start) != len(end) or int(end) - int(start) + 1 != count:
        raise ValueError('Fleet count and identifier pattern disagree')
    for n in range(int(start), int(end) + 1):
        vehicle = prefix + str(n).zfill(len(start))
        camera = _overview('BF01.' + vehicle, vehicle + ' · Flottenkamera',
                           {'id': 'BF01', 'room': 'Flotte nicht angebunden', 'level_id': None},
                           None, settings, 'fleet')
        camera.update(kind='modeled_camera', availability='not_connected',
                      near_mm=settings['near_mm'], far_mm=settings['modeled_far_mm'],
                      origin_label='Vorgesehene Modellkamera · Flotte nicht angebunden',
                      reason='Flotte nicht angebunden; kein Kamerabild vorhanden')
        cameras.append(camera)
    ids = [camera['id'] for camera in cameras]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate derived camera identifier')
    for camera in cameras:
        if camera['availability'] == 'missing_viewpoint':
            gaps.append({'device_id': camera['device_id'], 'reason': 'missing_viewpoint'})
    order = {'transporter': 0, 'robot': 1, 'device': 2, 'fleet': 3}
    cameras.sort(key=lambda camera: (order[camera['category']], camera['device_id'], camera['id']))
    defaults = [camera['id'] for camera in cameras if camera['availability'] == 'available'][:9]
    defaults += [None] * (9 - len(defaults))
    return {'format': FORMAT, 'id': spec['id'], 'cameras': cameras, 'gaps': gaps,
            'default_assignments': defaults, 'settings': dict(settings),
            'source_files_sha256': pins,
            'message_source_connected': False, 'fleet_connected': False,
            'qualification': {'hardware_executed': False, 'received_camera_frames': False,
                              'stationary_physical_cameras_modeled': False}}
