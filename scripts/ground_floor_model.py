"""Resolve an already aligned EG trace into the existing relative-plan contract.

The 180-degree registration is provenance, not a transform to apply again.
Original photographs are neither accepted inputs nor public dependencies.
"""
from pathlib import Path
import copy
import hashlib
import json

import assembly_model as assembly
import relative_floorplan as floor

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/ground-floor-eg.shared.json'
SCHEMA = ROOT/'model/ground-floor.schema.json'
FORMAT = 'solidcraftbot.registered-relative-floorplan/1'
REGISTRATION = {'orientation_deg': 180, 'applied_to_literals': True, 'basis': 'shared_vertical_cores', 'metric_scale_known': False, 'quality': 'concept_alignment'}


def require(condition, message):
    if not condition: raise ValueError(message)


def reference_plan(reference):
    require(isinstance(reference, dict) and set(reference) == {'source', 'source_sha256'}, 'Pinned F03 reference required')
    path = assembly.validate_reference(reference, root=ROOT)
    result = floor.load(path)
    require(result['_source']['sha256'] == reference['source_sha256'], 'Referenced relative plan changed while loading')
    return result


def resolve(source):
    expected = {'format', 'id', 'units', 'calibration', 'vertices', 'walls', 'areas', 'openings', 'provenance', 'reference_floorplan', 'registration'}
    require(isinstance(source, dict) and set(source) == expected and source['format'] == FORMAT, 'Registered relative EG source required')
    require(source['registration'] == REGISTRATION and source['registration']['applied_to_literals'] is True and source['registration']['metric_scale_known'] is False, 'Literal coordinates must already be registered, without metric calibration')
    reference = reference_plan(source['reference_floorplan'])
    require(isinstance(source['vertices'], dict), 'Vertex map required')
    vertices = {}
    for name, value in source['vertices'].items():
        if isinstance(value, dict):
            require(set(value) == {'reference_vertex'} and value['reference_vertex'] in reference['vertices'], 'Existing F03 vertex reference required')
            vertices[name] = copy.deepcopy(reference['vertices'][value['reference_vertex']])
        else:
            vertices[name] = copy.deepcopy(value)
    result = {key: copy.deepcopy(value) for key, value in source.items() if key not in {'reference_floorplan', 'registration'}}
    result['format'] = floor.FORMAT; result['vertices'] = vertices
    floor.validate(result)
    return result


def load(path=SOURCE):
    path = Path(path).resolve(); raw = path.read_bytes(); source = json.loads(raw)
    result = resolve(source); sha = hashlib.sha256(raw).hexdigest()
    require(floor.digest(path) == sha, 'Ground-floor source changed while loading')
    result['_source'] = {'path': str(path), 'sha256': sha}
    return result


def raw_source(plan):
    origin = plan.get('_source')
    require(isinstance(origin, dict) and set(origin) == {'path', 'sha256'}, 'Loaded ground-floor source required')
    raw = Path(origin['path']).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == origin['sha256'], 'Ground-floor source changed after loading')
    return json.loads(raw)


def registration(plan):
    return copy.deepcopy(raw_source(plan)['registration'])


def source_dependencies(plan):
    raw = raw_source(plan); reference = reference_plan(raw['reference_floorplan'])
    paths = [Path(plan['_source']['path']), SCHEMA, Path(__file__), ROOT/'scripts/assembly_model.py', ROOT/'model/assembly-reference.schema.json', *floor.source_dependencies(reference)]
    return list(dict.fromkeys(paths))
