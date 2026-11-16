#!/usr/bin/env python3
"""Render the checked camera revision on the frozen README motion program."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

import robot_cameras
import robot_components
import robot_spec

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'docs/media/robot-demo-continuous-cfr'
DEFAULT = ROOT / 'docs/media/robot-demo-cameras-aligned.html'
SCENE_REPORT = ROOT / 'exports/generated/cf01-camera-scene-report.json'
PRODUCERS = ['scripts/build_cf01_camera_demo.py', 'scripts/robot_cameras.py',
             'scripts/robot_components.py', 'scripts/robot_spec.py', 'scripts/assembly_model.py',
             'scripts/templates/centrifuge_robot_pickup.html', 'scripts/templates/robot_demo_header.html',
             'scripts/templates/quintic_motion.js', 'scripts/templates/robot_camera_views.js']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_mesh(path):
    packed = re.search(r'<script type="application/json" data-mesh>([^<]+)</script>', Path(path).read_text())[1]
    return json.loads(gzip.decompress(base64.b64decode(packed)))


def camera_metadata(mesh):
    spec = robot_spec.load(ROOT / mesh['scene']['sources']['robot'], mesh['scene'].get('robot_parameter_overrides_mm'))
    if robot_spec.parameters(spec) != mesh['robot_parameters']:
        raise ValueError('Frozen arm variant differs from the shared camera source')
    result = []
    for camera in robot_cameras.audit(spec)['cameras']:
        f = camera['optical_frame']
        x, y, z = robot_components.axes(f)
        group = 'Arm.' + camera['mounted_link']
        for suffix in ['_body_ENVELOPE', '_lens_ENVELOPE']:
            body = next(b for b in mesh['bodies'] if b['id'] == 'Arm.' + camera['id'] + suffix)
            if body['group'] != group:
                raise ValueError('Camera mesh is attached to a different link')
        result.append({**camera, 'group': group,
                       'optical_frame': {'r': [axis[i] for i in range(3) for axis in (x, y, z)], 'p': f['origin_mm']}})
    return result


def build(target=DEFAULT, scene_report=SCENE_REPORT):
    historical = json.loads(BASE.with_suffix('.provenance.json').read_text())
    if sha(BASE.with_suffix('.html')) != historical['media']['html']['sha256']:
        raise ValueError('Frozen geometry/motion HTML differs from its provenance')
    for name in ['scripts/robot_cameras.py', 'scripts/robot_spec.py',
                 'scripts/robot_components.py', 'scripts/templates/quintic_motion.js']:
        pins = historical['source_files_sha256']
        expected = pins.get(name) or historical['geometry']['geometry_sources_sha256'].get(name)
        if sha(ROOT / name) != expected:
            raise ValueError('Frozen camera/motion source changed: ' + name)
    geometry_report = json.loads(Path(scene_report).read_text())
    if not geometry_report['passed'] or geometry_report['preview_only']:
        raise ValueError('A passed native camera-scene check is required')
    if geometry_report['source_robot_sha256'] != sha(ROOT / 'model/robot.json'):
        raise ValueError('Checked camera source changed')
    for name, value in geometry_report['generator_sha256'].items():
        if sha(ROOT / name) != value: raise ValueError('Camera geometry producer changed: ' + name)
    mesh_path = ROOT / geometry_report['mesh']['path']
    if sha(mesh_path) != geometry_report['mesh']['sha256']:
        raise ValueError('Checked camera mesh changed')
    native = geometry_report['native_motion']
    if not native['passed'] or sha(ROOT / native['path']) != native['sha256']:
        raise ValueError('Camera motion evidence changed')
    mesh = json.loads(mesh_path.read_text())
    program_hash = canonical(mesh['unload_program'])
    if program_hash != historical['compiled_program']['canonical_sha256']:
        raise ValueError('Frozen motion payload differs from its native evidence')
    mesh['camera_views'] = camera_metadata(mesh)
    packed = base64.b64encode(gzip.compress(json.dumps(mesh, separators=(',', ':'), allow_nan=False).encode(), mtime=0)).decode()
    header = (ROOT / 'scripts/templates/robot_demo_header.html').read_text()
    scripts = '\n'.join((ROOT / name).read_text() for name in
                        ['scripts/templates/quintic_motion.js', 'scripts/templates/robot_camera_views.js'])
    template = (ROOT / 'scripts/templates/centrifuge_robot_pickup.html').read_text()
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header + '<script>\n' + scripts + '\n</script>\n' + template.replace('__MESH__', packed) + '\n</html>\n')
    if target.stat().st_size > 2_000_000:
        raise ValueError('Camera demo exceeds the 2 MB budget')
    result = {'format': 'solidcraftbot.camera-demo/2', 'scope': 'Current camera geometry; unchanged historical non-camera geometry and compiled motion, newly checked native motion',
              'base_media': {p.name: sha(p) for p in [BASE.with_suffix('.html'), BASE.with_suffix('.provenance.json')]},
              'source_files_sha256': {name: sha(ROOT / name) for name in ['model/robot.json', *PRODUCERS]},
              'compiled_program_canonical_sha256': program_hash,
              'geometry_canonical_sha256': canonical(mesh['bodies']), 'body_count': len(mesh['bodies']),
              'camera_views': mesh['camera_views'], 'html_sha256': sha(target), 'html_bytes': target.stat().st_size,
              'camera_scene': {'path': str(Path(scene_report).resolve().relative_to(ROOT)), 'sha256': sha(scene_report), 'report': geometry_report},
              'projection': 'Illustrative 16:9 pinhole sensor inscribed in source circular cone, letterboxed on resize; optical +Z forward, +X right, +Y down; 0.5–5000 mm render clipping, no measured sensor range',
              'occlusion': 'Depth-tested opaque mesh surfaces, including robot, gripper and equipment; display cones excluded',
              'limitations': ['No calibrated intrinsics, distortion, focus, lighting or real camera data',
                              'Discrete native collision/clearance checks; no continuous collision guarantee or safety qualification',
                              'Wide-angle workspace observation is an intended use; no hazard detector or protective stop is implemented']}
    target.with_suffix('.provenance.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    return result


def bind_capture(target, capture_path, browser_path):
    """Bind the actual CFR export and browser checks to this exact HTML."""
    report_path = target.with_suffix('.provenance.json')
    report = json.loads(report_path.read_text())
    capture = json.loads(capture_path.read_text())
    browser = json.loads(browser_path.read_text())
    manifest_path = Path(capture['frame_manifest'])
    manifest = json.loads(manifest_path.read_text())
    if (manifest['input_sha256'] != report['html_sha256'] or browser['html_sha256'] != report['html_sha256']
            or capture['source_scene_sha256'] != report['compiled_program_canonical_sha256']
            or capture['errors'] or not browser['passed'] or browser['errors']
            or sha(manifest_path) != capture['frame_manifest_sha256']):
        raise ValueError('Capture/browser evidence does not match this HTML')
    if capture['camera_ids'] != [c['id'] for c in report['camera_views']]:
        raise ValueError('Video is missing a camera view')
    if len(manifest['frames']) != capture['frames'] or any(abs(f['camera_time_s'] - f['source_time_s']) > 1e-9 for f in manifest['frames']):
        raise ValueError('Camera clocks differ from the recorded motion')
    video = Path(capture['video'])
    probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames,duration',
        '-of', 'json', str(video)], check=True, capture_output=True, text=True).stdout)['streams'][0]
    if (probe['codec_name'] != 'h264' or int(probe['nb_read_frames']) != capture['frames']
            or probe['r_frame_rate'] != str(capture['encoding']['fps']) + '/1'
            or abs(float(probe['duration']) - capture['video_target_duration_s']) > .001):
        raise ValueError('Encoded MP4 differs from the capture schedule')
    report['media'] = {kind: {'path': str(p.relative_to(ROOT)), 'sha256': sha(p), 'bytes': p.stat().st_size}
                       for kind, p in [('html', target), ('video', video), ('poster', Path(capture['screenshot']))]}
    report['capture'] = {k: v for k, v in capture.items() if k not in ['states', 'input', 'video', 'screenshot', 'frame_manifest']}
    report['capture']['frame_manifest'] = str(manifest_path.relative_to(ROOT))
    report['capture']['ffprobe'] = probe
    report['browser_validation'] = browser
    report['validation_sources_sha256'] = {name: sha(ROOT / name) for name in
        ['scripts/export_readme_video.cjs', 'tests/check_cf01_camera_views.cjs',
         'tests/test_cf01_camera_demo.py', 'tests/check_readme_video_export.cjs']}
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    parser.add_argument('--capture-report', type=Path)
    parser.add_argument('--browser-report', type=Path)
    parser.add_argument('--camera-scene-report', type=Path, default=SCENE_REPORT)
    args = parser.parse_args()
    if bool(args.capture_report) != bool(args.browser_report):
        parser.error('--capture-report and --browser-report must be supplied together')
    args.output = args.output.resolve()
    report = build(args.output, args.camera_scene_report)
    if args.capture_report:
        bind_capture(args.output, args.capture_report, args.browser_report)
    print(json.dumps({'html': str(args.output), 'bytes': report['html_bytes'], 'cameras': len(report['camera_views'])}))
