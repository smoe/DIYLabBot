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


def validate(source, verify_pins=True):
    validate_shape(source, read_json(SCHEMA))
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
    return source


def load(path=SOURCE):
    return validate(read_json(path))


def reference(source, key):
    return read_json(resolve_pin(source['sources'][key]))


def resolved_sensor(source):
    ref = reference(source, 'sensor')
    sensor = copy.deepcopy(ref['sensor'])
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
