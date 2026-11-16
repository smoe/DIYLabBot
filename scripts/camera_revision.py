"""Prove a camera-only source revision before reusing non-camera geometry."""
import copy
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unchanged_arm(spec):
    value = copy.deepcopy(spec)
    value['parameters'] = {k: v for k, v in value['parameters'].items() if not k.startswith('cam_')}
    for link in value['links']:
        link['recipe'] = [op for op in link['recipe'] if op['action'] != 'camera']
    # A camera dimension must not secretly drive any retained mechanical part.
    if 'cam_' in json.dumps(value):
        raise ValueError('Camera parameters are referenced outside camera operations')
    return value


def verify(previous_path, current_path, expected_previous):
    if sha(previous_path) != expected_previous:
        raise ValueError('Historical arm source does not match its geometry pin')
    previous = json.loads(Path(previous_path).read_text())
    current = json.loads(Path(current_path).read_text())
    if unchanged_arm(previous) != unchanged_arm(current):
        raise ValueError('Non-camera arm construction changed; rebuild the complete scene')
    return {'previous_sha256': expected_previous, 'current_sha256': sha(current_path),
            'non_camera_source_equal': True,
            'scope': 'Only camera operations and exclusively camera parameters may differ; replace all camera bodies before motion validation'}
