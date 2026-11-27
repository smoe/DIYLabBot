"""Strict, standard-library BF01 source contract; no effects or CAD imports."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/building-fleet-demo.shared.json'
SCHEMA = ROOT/'model/building-fleet-demo.schema.json'
PROTECTED = ('sample_transport_model.py', 'sample_motion.py', 'cf01_unload_path.py',
             'tr01_floor_motion.py', 'tr01_workcell.py', 'l01_local_traffic.py',
             'l01_opposing_traffic.py', 'l01_independent_fleet.py', 'robot_spec.py',
             'assembly_model.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field: '+key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))


def validate_shape(value, schema, where='$'):
    """Evaluate only the closed schema vocabulary used by this contract.

    Unknown schema keywords fail rather than silently skipping validation.
    No dependency on optional jsonschema or CAD runtimes.
    """
    supported = {'$schema', 'title', 'description', 'type', 'properties', 'required',
                 'additionalProperties', 'items', 'minItems', 'maxItems',
                 'minimum', 'maximum', 'minLength', 'pattern', 'const', 'enum'}
    if set(schema)-supported:
        raise ValueError('Unsupported BF01 schema keyword at '+where)
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise ValueError('Unexpected constant at '+where)
    if 'enum' in schema and not any(type(value) is type(x) and value == x for x in schema['enum']):
        raise ValueError('Unknown choice at '+where)
    kind = schema.get('type')
    checks = {'object': lambda: type(value) is dict, 'array': lambda: type(value) is list,
              'string': lambda: type(value) is str, 'boolean': lambda: type(value) is bool,
              'integer': lambda: type(value) is int,
              'number': lambda: type(value) in (int, float) and math.isfinite(value)}
    if kind and (kind not in checks or not checks[kind]()):
        raise ValueError('Invalid '+str(kind)+' at '+where)
    if kind == 'object':
        props = schema['properties']
        if not set(schema['required']) <= set(value):
            raise ValueError('Missing field at '+where)
        if schema.get('additionalProperties') is not False or set(value)-set(props):
            raise ValueError('Unexpected field at '+where)
        for key, item in value.items():
            validate_shape(item, props[key], where+'.'+key)
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', math.inf):
            raise ValueError('Invalid array size at '+where)
        for index, item in enumerate(value):
            validate_shape(item, schema['items'], where+'['+str(index)+']')
    elif kind == 'string':
        if len(value) < schema.get('minLength', 0) or ('pattern' in schema and not re.fullmatch(schema['pattern'], value)):
            raise ValueError('Invalid string at '+where)
    elif kind in ('integer', 'number'):
        if not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):
            raise ValueError('Value outside declared range at '+where)
    return value


def resolve_pin(ref):
    path = (ROOT/ref['path']).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or digest(path) != ref['sha256']:
        raise ValueError('Changed, missing or external BF01 source: '+ref['path'])
    return path


def scan_beam_count(step_deg):
    if type(step_deg) not in (int, float) or not math.isfinite(step_deg) or not .36 <= step_deg <= 360:
        raise ValueError('A bounded full-circle beam step is required')
    count = round(360 / step_deg)
    if not math.isclose(count * step_deg, 360., rel_tol=0, abs_tol=1e-12):
        raise ValueError('The BF01 synthetic scan must cover the full circle')
    return count


def validate(source, verify_pins=True):
    validate_shape(dict(source) if isinstance(source, _PatrolSource) else source, read_json(SCHEMA))
    if verify_pins:
        for ref in source['sources'].values():
            resolve_pin(ref)
    keys = [(r['level'], r['area']) for r in source['missions']['targets']]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate target')
    expected = {('EG', a) for a in ('R0_001', 'R0_002', 'R0_003', 'R0_015', 'R0_014A')}
    expected |= {(level, a) for level in ('OG1', 'OG2', 'OG3') for a in ('R3_001', 'R3_003', 'R3_007')}
    expected |= {('KG', a) for a in ('K0_002', 'K0_006', 'K0_009', 'K0_012', 'K0_011')}
    if set(keys) != expected:
        raise ValueError('All non-deferred E1/E2 targets are mandatory')
    if len(source['missions']['deferred_targets']) != 1:
        raise ValueError('Only explicitly deferred K0_013 may be omitted')
    for row in source['missions']['targets']:
        basis = 'template_area_use_unconfirmed' if row['level'] in ('OG1', 'OG2') else 'owner_description' if row['level'] == 'OG3' else 'plan_label'
        if row['basis'] != basis:
            raise ValueError('Area use basis changed: '+str((row['level'], row['area'])))
    if source['missions']['minimum_duration_s'] >= source['missions']['maximum_duration_s']:
        raise ValueError('Bounded mission duration required')
    latency = source['communication']['latency_s']
    if latency[0] > latency[1]:
        raise ValueError('Latency interval inverted')
    policy = source['sensor']
    extension = policy.get('synthetic_scan')
    if (policy['basis'] == 'bf01_synthetic_long_range') != (extension is not None):
        raise ValueError('Declare the BF01-only scan model and its basis together')
    if extension is not None:
        scan_beam_count(extension['angular_step_deg'])
        if extension['maximum_obstacle_closing_speed_mm_s'] < source['motion']['empty_linear_limits']['velocity_mm_s']:
            raise ValueError('The BF01 scan must cover a vehicle approaching from a faster zone')
        layout_sensor = resolved_sensor(source, for_layout=True)
        if scan_angular_allowance(extension) > scan_angular_allowance(layout_sensor):
            raise ValueError('The BF01 scan uncertainty exceeds the layout passing allowance')
    elif source['motion']['empty_linear_limits']['velocity_mm_s'] > 1000:
        raise ValueError('The legacy scan cannot accompany an extended BF01 speed ceiling')
    return source


def load(path=SOURCE):
    return validate(read_json(path))


def reference(source, key):
    return read_json(resolve_pin(source['sources'][key]))


def patrol_policy(profile):
    """Validate the active patrol policy, including profiles preceding variable corner timing."""
    if 'vehicle_count' in profile:
        count = profile['vehicle_count']
        if type(count) is not int or count not in (6, 20):
            raise ValueError('The patrol vehicle_count must be exactly six or twenty')
    timing = patrol_timing(profile)
    policy = profile.get('patrol', {})
    startup = policy.get('startup')
    expected = {'termination': 'explicit_stop', 'startup': startup, 'targets': '/missions/targets',
                'selection': 'oldest_received_visit'}
    if 'corner_timing' in policy:
        expected['corner_timing'] = 'variable_progress'
    if 'ground_boarding' in policy:
        boarding = policy['ground_boarding']
        slots = ('waiting_slot', 'cabin_slot')
        distances = ('departure_lead_mm', 'alignment_from_port_mm')
        fraction = 'aperture_center_fraction'
        if (timing is None or type(boarding) is not dict or set(boarding) != {*slots, *distances, fraction}
                or any(type(boarding[name]) is not int or boarding[name] < 0 for name in slots)
                or any(type(boarding[name]) not in (int, float) or not math.isfinite(boarding[name])
                       or boarding[name] <= 0 for name in distances)
                or type(boarding[fraction]) not in (int, float) or not 0 < boarding[fraction] <= 1):
            raise ValueError('Invalid live ground-floor boarding route')
        expected['ground_boarding'] = boarding
    if startup not in ('first_received_camera_frames', 'own_received_camera_frame') or policy != expected:
        raise ValueError('Unsupported continuous empty-patrol policy')
    return policy


def active_vehicle_ids(source, profile=None):
    """Select live occupants without changing the twenty-place reference source.

    Profiles preceding the explicit selection retain the complete reference
    fleet. The profile selects existing identities, never new home geometry.
    """
    maximum = source['fleet']['count']
    count = maximum
    if profile is not None:
        patrol_policy(profile)
        count = profile.get('vehicle_count', maximum)
    if type(maximum) is not int or maximum != 20 or type(count) is not int or count not in (6, maximum):
        raise ValueError('A six- or twenty-vehicle patrol needs the twenty-place reference fleet')
    return tuple('BF%02d' % i for i in range(1, count + 1))


def patrol_timing(profile):
    timing = profile.get('timing')
    if 'timing' in profile and (profile.get('vehicle_count') != 6 or timing != {
            'ground_step_ms': 400, 'scan_latency_ms': 50, 'maximum_scan_age_ms': 450}):
        raise ValueError('The tested live timing requires the six-vehicle patrol')
    return timing


class _PatrolSource(dict):
    # Keep runtime timing separate from serialized native geometry and source pins.
    pass


def patrol_source(source, profile):
    timing = patrol_timing(profile)
    if timing is None:
        return source
    scoped = _PatrolSource(source)
    scoped.timing = timing.copy()
    return scoped


def control_step_s(source):
    timing = getattr(source, 'timing', None)
    return timing['ground_step_ms']/1000 if timing else .05


def lift_route_ports(source, ports):
    """Select the traversed landing on each level independently of the door cycle."""
    sides = source['lift'].get('route_sides', {})
    active = {}
    for port in ports:
        if port['active']:
            active.setdefault(port['level_id'], []).append(port)
    if set(sides) - set(active):
        raise ValueError('Configured BF01 route side has no active lift level')
    result = {}
    for level, choices in active.items():
        if level in sides:
            choices = [port for port in choices if port['side'] == sides[level]]
        if len(choices) != 1:
            raise ValueError('One unambiguous BF01 route port required: ' + level)
        result[level] = choices[0]
    return result


def lift_open_sides_by_level(ports):
    """Return the simultaneous opening configuration for each docked floor."""
    sides_by_level = {}
    for port in ports:
        if port['active']:
            sides_by_level.setdefault(port['level_id'], set()).add(port['side'])
    return {level: tuple(sorted(sides)) for level, sides in sides_by_level.items()}


def lift_scan_side_sets(ports):
    """Include the physical door set at every stop in scan geometry."""
    return sorted({(), ('inward',), ('outward',),
                   *lift_open_sides_by_level(ports).values()})


def scan_angular_allowance(sensor):
    return sensor['range_mm'] * math.sin(math.radians(sensor['angular_step_deg']))


def resolved_sensor(source, *, for_layout=False):
    """Keep the original E5 spacing assumptions for static path construction."""
    ref = reference(source, 'sensor')
    sensor = copy.deepcopy(ref['sensor'])
    if not for_layout:
        sensor.update(source['sensor'].get('synthetic_scan', {}))
        timing = getattr(source, 'timing', None)
        if timing is not None:
            sensor.update(latency_s=timing['scan_latency_ms']/1000,
                          stale_after_s=timing['maximum_scan_age_ms']/1000)
    sensor['clearance_mm'] = ref['controller']['clearance_mm']
    return sensor


def admission_settings(source):
    """Resolve the source-owned mission and conditional bay lifecycle policy."""
    validate(source)
    return copy.deepcopy(source['missions']['admission_policy'])


def source_pins(source):
    return {**{ref['path']: ref['sha256'] for ref in source['sources'].values()},
            str(SOURCE.relative_to(ROOT)): digest(SOURCE),
            str(SCHEMA.relative_to(ROOT)): digest(SCHEMA),
            'scripts/building_fleet_model.py': digest(__file__)}


def protected_pins():
    return {'scripts/'+name: digest(ROOT/'scripts'/name) for name in PROTECTED}


def support_settings(source):
    """Resolve the owner support policy without copying the source lift height."""
    validate(source)
    result=copy.deepcopy(source['support_rule'])
    result['closing_radius_mm']=result['gap']['maximum']/2
    return result
