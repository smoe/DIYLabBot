"""Current camera geometry in the pinned historical CF01 demonstration scene.

Only cameras are replaced. All other native geometry and the compiled motion
remain explicitly historical inputs; current furniture is not substituted.
"""
import FreeCAD as App
import Part
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import camera_revision
import robot_cameras
import robot_spec as robot
import build_cf01_camera_demo as demo
import cf01_unload_geometry as geometry
import cf01_unload_motion as motion
import check_cf01_unload_motion as check

ROOT = robot.ROOT
BASE_SOURCE = ROOT / 'exports/generated/2fa84f950446/model-source.json'
LATEST = ROOT / 'exports/generated/cf01-camera-scene-report.json'


def checked(path, expected):
    path = geometry.project(path)
    if geometry.sha(path) != expected:
        raise ValueError('Historical input changed: ' + str(path))
    return path


def inputs():
    p = json.loads(demo.BASE.with_suffix('.provenance.json').read_text())
    checked(p['media']['html']['path'], p['media']['html']['sha256'])
    mesh = demo.read_mesh(demo.BASE.with_suffix('.html'))
    delta = camera_revision.verify(BASE_SOURCE, robot.SPEC, p['source_files_sha256']['model/robot.json'])
    if demo.canonical(mesh['unload_program']) != p['compiled_program']['canonical_sha256']:
        raise ValueError('Historical compiled motion changed')
    # Bind FK/geometry interpretation to the historical implementation, too.
    for name in ['scripts/robot_spec.py', 'scripts/robot_cameras.py', 'scripts/centrifuge_robot_pickup.py']:
        checked(name, p['geometry']['geometry_sources_sha256'][name])
    for name in ['scripts/cf01_unload_motion.py', 'scripts/sample_motion.py', 'scripts/templates/quintic_motion.js']:
        checked(name, p['source_files_sha256'][name])
    files = {key: checked(value['path'], value['sha256']) for key, value in p['geometry']['artifacts'].items()}
    bundle = {'files': files, 'mesh': geometry.read(files['mesh']),
              'old_scene': geometry.read(files['old_scene']), 'old_trajectory': geometry.read(files['old_trajectory'])}
    # Native instrument bodies and placements are frozen; only their unchanged
    # component mathematics is used for the conservative NanoDrop hinge sweep.
    ip = p['instruments']
    archived_report = ROOT / 'exports/generated' / Path(ip['native']).parent.name / 'build-report.json'
    report = geometry.read(checked(archived_report, ip['report_sha256']))
    native = checked(ip['native'], ip['native_sha256'])
    import synthetic_lab_scene as layout
    import instrument_concept as instruments
    for name in ['scripts/synthetic_lab_scene.py', 'scripts/instrument_concept.py']:
        checked(name, ip['geometry_sources_sha256'][name])
    entries = []; manifest = {}
    for name, binding in report['source_bindings'].items():
        source = checked(binding['source'], binding['source_sha256'])
        spec = instruments.load(source); parameters = instruments.parameters(spec)
        asset = next(key for key, family in layout.INSTRUMENT_ASSETS.items() if family == spec['family'])
        if instruments.pose(spec, parameters)['Hinge'] != ip['poses'][name]['hinge_deg']:
            raise ValueError('Historical instrument hinge pose changed')
        entry = {'instance': {'id': name, 'asset': asset, 'matrix': report['instance_poses'][name]},
                 'spec': spec, 'parameters': parameters}
        entries.append(entry)
        for body in instruments.expanded(entry['spec'], entry['parameters'])['bodies']:
            manifest[name + '.' + body['id']] = {'instance': name, 'component': body['component'],
                'role': body['role'], 'appearance': body['appearance']}
    expected = {b['instance'] + '.' + b['source_body'] for b in report['body_manifest'] if b['instance'] in report['source_bindings']}
    if expected != set(manifest): raise ValueError('Frozen instrument body manifest mismatch')
    return mesh, bundle, {'native': native, 'entries': entries, 'manifest': manifest}, delta


def camera_shapes(App, Part, spec):
    p = robot.parameters(spec); expanded = robot_cameras.lower(spec)
    result = []
    for link in expanded['links']:
        for op in link['recipe']:
            if op.get('role') not in ('camera_envelope', 'camera_mount'): continue
            primitive = op['primitive']; origin = [robot.evaluate(v, p) for v in primitive['origin']]
            if primitive['kind'] == 'box':
                shape = Part.makeBox(*[robot.evaluate(v, p) for v in primitive['size']])
                if 'axis' in primitive:
                    shape.Placement = check._placement(App, robot.frame({'frame': primitive}, p))
                else: shape.Placement.Base = App.Vector(*origin)
            elif primitive['kind'] == 'cylinder':
                shape = Part.makeCylinder(robot.evaluate(primitive['radius'], p), robot.evaluate(primitive['length'], p),
                    App.Vector(*origin), App.Vector(*primitive['axis']))
            else: raise ValueError('Unsupported camera primitive')
            appearance = expanded['body_appearances'][op['body']]
            minimum, maximum = check._box(shape)
            result.append({'id': 'Arm.' + op['body'], 'group': 'Arm.' + link['id'], 'kind': 'arm',
                'role': op['role'], 'sample_id': None, 'shape': shape, 'minimum': minimum, 'maximum': maximum,
                'appearance': {'color': '#' + ''.join('%02x' % v for v in appearance['color']), 'opacity': appearance['opacity']}})
    return result


def replace_mesh(mesh, cameras, spec):
    updated = copy.deepcopy(mesh)
    updated['bodies'] = [b for b in mesh['bodies'] if b['role'] not in ('camera_envelope', 'camera_mount')]
    for camera in cameras:
        vertices, faces = camera['shape'].tessellate(.15)
        updated['bodies'].append({'id': camera['id'], 'group': camera['group'], 'asset': 'arm', 'role': camera['role'],
            **camera['appearance'], 'v': [[v.x, v.y, v.z] for v in vertices], 'f': [list(f) for f in faces]})
    updated['robot_parameters'] = robot.parameters(spec)
    groups = {}
    for body in updated['bodies']: groups.setdefault(body['group'], []).extend(body['v'])
    import itertools
    updated['group_bounds'] = {group: [list(v) for v in itertools.product(*[
        (min(v[i] for v in points), max(v[i] for v in points)) for i in range(3)])] for group, points in groups.items()}
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-only', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    mesh, bundle, instruments, delta = inputs()
    producer_pins = {name: geometry.sha(ROOT / name) for name in
        ['scripts/build_cf01_camera_scene.py', 'scripts/camera_revision.py', 'scripts/check_cf01_unload_motion.py']}
    spec = robot.load(robot.SPEC, mesh['scene'].get('robot_parameter_overrides_mm'))
    cameras = camera_shapes(App, Part, spec)
    out = (args.out or ROOT / 'exports/generated' / ('cf01-cameras-' + robot.digest(robot.SPEC)[:12])).resolve()
    out.mkdir(parents=True, exist_ok=True)
    revised = replace_mesh(mesh, cameras, spec)
    mesh_path = out / 'scene-mesh.json'
    mesh_path.write_text(json.dumps(revised, separators=(',', ':')))
    report = {'format': 'solidcraftbot.cf01-camera-scene/1', 'passed': False, 'preview_only': args.preview_only,
        'camera_source_delta': delta, 'source_robot_sha256': robot.digest(robot.SPEC),
        'historical_provenance_sha256': geometry.sha(demo.BASE.with_suffix('.provenance.json')),
        'mesh': {'path': str(mesh_path.relative_to(ROOT)), 'sha256': geometry.sha(mesh_path)},
        'program_canonical_sha256': demo.canonical(mesh['unload_program']),
        'camera_body_ids': [r['id'] for r in cameras],
        'scope': 'Current camera bodies in the frozen historical CF01 scene; unchanged arm mechanics and compiled motion'}
    if not args.preview_only:
        records = check.load_records(App, bundle, instruments, mesh['unload_program'])
        records = [r for r in records if r['role'] not in ('camera_envelope', 'camera_mount')] + cameras
        report['body_coverage'] = {'total': len(records), 'cameras': len(cameras),
            'sample_bodies': sorted(r['id'] for r in records if r.get('sample_id')),
            'instrument_envelopes': sorted(r['id'] for r in records if r['kind'] == 'instrument_envelope')}
        print('Checking complete motion with revised cameras...', flush=True)
        audit = check.audit(App, mesh['unload_program'], records)
        audit_path = out / 'native-motion-validation.json'
        audit_path.write_text(json.dumps(audit, indent=2, allow_nan=False) + '\n')
        report['native_motion'] = {'path': str(audit_path.relative_to(ROOT)), 'sha256': geometry.sha(audit_path),
            'passed': audit['passed'], 'frames': audit['requested_frames'], 'collisions': len(audit['collisions']),
            'distance_failures': len(audit['distance_failures'])}
        report['passed'] = audit['passed']
        report['posed_models'] = []
        if audit['passed']:
            program = mesh['unload_program']; evaluate = motion.SceneEvaluator(program['scene'], program)
            for name, time in [('Grasp', program['transfers'][0]['gripped_s']), ('Final', program['duration_s'])]:
                report['posed_models'].append(check.save_pose(App, program, records, evaluate, time,
                    out / ('CF01_Cameras_' + name + '.FCStd'), report['program_canonical_sha256']))
    if inputs()[3] != delta:
        raise ValueError('Camera source changed during the native check')
    for name, value in producer_pins.items():
        if geometry.sha(ROOT / name) != value: raise ValueError('Native producer changed during check: ' + name)
    report['generator_sha256'] = producer_pins
    destination = out / 'camera-scene-report.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    if report['passed']: LATEST.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(destination), 'passed': report['passed'], 'preview_only': args.preview_only}), flush=True)
    if not args.preview_only and not report['passed']: raise SystemExit('Revised cameras failed native motion checks')


if __name__ == '__main__': main()
