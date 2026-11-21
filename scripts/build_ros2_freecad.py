"""Generate the arm's ROS assets directly from shared sources using FreeCAD.

This independent entry point needs neither SolidCraft nor an earlier native
build report. It checks static BRep validity and home-frame agreement only;
colcon/package/controller checks belong to the separate ROS CI stage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import robot_spec as model
import robot_components
import build_ros2
import tool_paths
from build_instrument_concepts import freecad_environment

ROOT = model.ROOT


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def source_snapshot(spec):
    paths = [model.SPEC, ROOT/'model/robot.schema.json', Path(__file__)]
    paths += [ROOT/'scripts'/name for name in (
        'robot_spec.py', 'assembly_model.py', 'robot_components.py', 'robot_cameras.py',
        'robot_services.py', 'servo_mounting_design.py', 'x6_mounting_design.py',
        'build_neutral_freecad.py', 'build_ros2.py', 'build_instrument_concepts.py',
        'tool_paths.py', 'freecad/solidcraftbot_freecad.py')]
    if 'vendor_library' in spec:
        paths.append(ROOT/spec['vendor_library']['path'])
        for part in robot_components.library(spec)['parts'].values():
            paths += [ROOT/part[key]['path'] for key in ('interface_spec', 'interface_check') if key in part]
            paths += [ROOT/section['step'] for section in part['sections'].values()]
    return {str(p.relative_to(ROOT)): model.digest(p) for p in dict.fromkeys(paths)}


def verify_pins(pins):
    for name, expected in pins.items():
        if model.digest(ROOT/name) != expected:
            raise ValueError('ROS export input changed during build: '+name)


def native_export(request_path):
    import FreeCAD as App
    import build_neutral_freecad as native
    import solidcraftbot_freecad as geometry
    request = json.loads(request_path.read_text())
    verify_pins(request['source_files_sha256'])
    spec = model.load()
    output = ROOT/request['native_file']
    doc = native.build(spec, output)
    try:
        bodies = geometry.features(doc)
        checks = [{'body': o.SourceBody, 'valid': o.Shape.isValid(),
                   'solid_count': len(o.Shape.Solids)} for o in bodies]
        if not checks or any(not c['valid'] or c['solid_count'] < 1 for c in checks):
            raise ValueError('Invalid or empty native arm BRep')
        expected = model.forward(spec, model.home(spec))
        errors = []
        for name, frame in expected.items():
            placed = geometry.global_placement(doc.getObject(name))
            for point in ([0, 0, 0], [17, 0, 0], [0, 23, 0], [0, 0, 31]):
                actual = placed.multVec(App.Vector(*point))
                errors.append((actual-App.Vector(*model.transform(frame, point))).Length)
        if max(errors) > .01:
            raise ValueError('Native home frames differ from shared forward kinematics')
    finally:
        App.closeDocument(doc.Name)
    native.export_ros_geometry(spec, output, build_ros2.PACKAGE)
    verify_pins(request['source_files_sha256'])
    write(ROOT/request['native_report'], {'passed': True, 'backend': 'freecad',
        'freecad_version': App.Version(), 'bodies': checks,
        'maximum_home_frame_error_mm': max(errors), 'source_files_sha256': request['source_files_sha256'],
        'scope': 'Static native BRep validity and home FK agreement; no motion sweep or cross-CAD comparison.'})


def build(freecad_python):
    spec = model.load()
    pins = source_snapshot(spec)
    key = hashlib.sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()[:12]
    base = ROOT/'exports/generated'/('ros2-freecad-'+key)
    output, count = base, 1
    while output.exists():
        count += 1
        output = base.with_name(base.name+'-r'+str(count))
    output.mkdir(parents=True)
    for directory in ('config', 'urdf', 'meshes'):
        (build_ros2.PACKAGE/directory).mkdir(parents=True, exist_ok=True)
    request = {'source_files_sha256': pins, 'native_file': str((output/'arm.FCStd').relative_to(ROOT)),
               'native_report': str((output/'native-report.json').relative_to(ROOT))}
    write(output/'request.json', request)
    subprocess.run([str(freecad_python), str(Path(__file__).resolve()), '--native-export',
                    str(output/'request.json')], check=True, cwd=ROOT,
                   env=freecad_environment(freecad_python))
    geometry = json.loads((build_ros2.PACKAGE/'config/geometry.json').read_text())
    if geometry.get('spec_sha256') != pins[str(model.SPEC.relative_to(ROOT))]:
        raise ValueError('ROS mesh export belongs to another arm source')
    build_ros2.generate(spec, geometry)
    verify_pins(pins)
    files = {'native_file': ROOT/request['native_file'], 'native_report': ROOT/request['native_report']}
    for directory in ('urdf', 'meshes', 'config'):
        for path in sorted((build_ros2.PACKAGE/directory).rglob('*')):
            if path.is_file():
                files[str(path.relative_to(build_ros2.PACKAGE))] = path
    report = {'format': 'solidcraftbot.ros2-freecad-build/1', 'passed': True,
              'source_sha256': pins[str(model.SPEC.relative_to(ROOT))], 'source_files_sha256': pins,
              'backend': 'freecad', 'cross_cad_checked': False, 'ros_runtime_tested': False,
              'files': {key: str(path.relative_to(ROOT)) for key, path in files.items()},
              'artifact_sha256': {key: model.digest(path) for key, path in files.items()},
              'scope': 'Native arm to ROS URDF/meshes/config; static validity and home frames only.',
              'limitations': ['No motion sweep, controller execution, hardware or dynamics qualification.',
                              'Legacy joint_linear scenarios are exported as data, not executed here.']}
    write(output/'build-report.json', report)
    write(ROOT/'exports/ros2-ci/build-report.json', report)
    print('Independent FreeCAD ROS export:', output/'build-report.json', flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad-python', type=Path, default=tool_paths.default_freecad_python())
    args = parser.parse_args()
    if not args.freecad_python:
        parser.error('A FreeCAD Python runtime is required')
    build(args.freecad_python)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--native-export':
        native_export(Path(sys.argv[2]))
    else:
        main()
