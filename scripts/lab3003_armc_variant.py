"""Bind the existing CF01 workspace arm variant to the Lab 3.003 demo."""

import json
import math
from pathlib import Path

import assembly_model as assembly
import building_laboratories as laboratories
import export_building_walkthrough_freecad as mesh
import lab_layout_model as layout
import robot_components
import robot_spec as robot
import synthetic_workspace as workspace


ROOT = robot.ROOT
SOURCE = ROOT / 'model/lab3003-armc-variant.shared.json'
NATIVE_FORMAT = 'solidcraftbot.lab3003-armc-native/1'


def _pose_matches(left, right):
    mesh.validate_rigid(left)
    mesh.validate_rigid(right)
    return all(math.isclose(a, b, rel_tol=0, abs_tol=1e-8)
               for row, other in zip(left, right) for a, b in zip(row, other))


def bind(lab):
    """Return the dimensioned arm and exact unchanged room and world poses."""
    definition = json.loads(SOURCE.read_text(encoding='utf-8'))
    if (set(definition) != {'format', 'laboratory_id', 'device_id', 'variant_device_id', 'sources'}
            or definition['format'] != 'solidcraftbot.lab3003-armc-variant/1'
            or (definition['laboratory_id'], definition['device_id'], definition['variant_device_id'])
            != ('Lab3003', 'ArmC', 'Arm')):
        raise ValueError('The ArmC geometry variant is local to Lab 3.003')
    refs = definition['sources']
    if set(refs) != {'laboratories', 'workspace'} or lab['id'] != definition['laboratory_id']:
        raise ValueError('The pinned Lab 3.003 and workspace sources are required')
    laboratory_path = assembly.validate_reference(refs['laboratories'])
    workspace_path = assembly.validate_reference(refs['workspace'])
    declaration, = (item for item in json.loads(laboratory_path.read_text())['laboratories']
                    if item['id'] == lab['id'])
    bench = declaration['bench_layout']
    device_id = definition['device_id']
    variant_id = definition['variant_device_id']
    if (bench['workspace'] != refs['workspace'] or bench['devices'].get(device_id) != variant_id
            or lab['layout_source'] != declaration['layout_source']):
        raise ValueError('The geometry variant must take the ArmC type and dimensions from its bench reference')
    source = workspace.load(workspace_path)
    donor = source['devices'][variant_id]
    layout_path = assembly.validate_reference(lab['layout_source'])
    if layout_path != layout.SOURCE:
        raise ValueError('The variant needs the unchanged standalone L01 reference')
    stock = json.loads(layout_path.read_text())
    stock_item, = (item for item in stock['instances'] if item['id'] == device_id)
    if (donor['asset'] != 'arm' or stock_item['asset'] != 'arm'
            or assembly.validate_reference(donor['source']) != assembly.validate_reference(stock['assets']['arm'])
            or set(donor.get('overrides', {})) != {'upper_len', 'fore_len'}):
        raise ValueError('The workspace arm must select the same geometry by its two driving link lengths')
    arm = assembly.load_instance(robot, donor['source'], donor['overrides'])
    device, = (item for item in lab['device_instances'] if item['id'] == device_id)
    context = layout.parameters(stock, room_overrides=lab['bound_parameters_mm'])
    base = laboratories.bench_poses(bench, stock['instances'], context)[device_id]
    world = robot.multiply(lab['transform'], base)
    park = bench['park_joints_deg'][device_id]
    body_prefix = lab['id'] + '_' + device_id + '_'
    if (device.get('direct_mount') is not True or device['host'] != stock_item['host']
            or device.get('park_joints_deg') != park or device['body_prefix'] != body_prefix
            or not _pose_matches(device['bound_pose'], base) or not _pose_matches(device['world_pose'], world)
            or len(park) != len(arm['joints'])
            or any(not joint['limits_deg'][0] <= q <= joint['limits_deg'][1]
                   for q, joint in zip(park, arm['joints']))):
        raise ValueError('The variant needs the checked direct mount and park configuration')
    paths = {SOURCE, laboratory_path, layout_path, workspace_path,
             *workspace.source_dependencies(source),
             *(ROOT / 'scripts' / name for name in (
                 'assembly_model.py', 'building_laboratories.py', 'furniture_model.py',
                 'lab3003_armc_variant.py', 'lab_layout_model.py', 'robot_cameras.py', 'robot_components.py',
                 'robot_services.py', 'robot_spec.py', 'servo_mounting_design.py',
                 'synthetic_workspace.py', 'x6_mounting_design.py'))}
    paths.add(ROOT / arm['vendor_library']['path'])
    for part in robot_components.library(arm)['parts'].values():
        paths.update(ROOT / part[key]['path'] for key in ('interface_spec', 'interface_check') if key in part)
        paths.update(ROOT / section['step'] for section in part['sections'].values())
    return {'arm': arm, 'laboratory_id': lab['id'], 'device_id': device_id,
            'body_prefix': body_prefix, 'level_id': lab['level_id'],
            'bound_pose': base, 'world_pose': world, 'park_joints_deg': park,
            'exclude_bodies': stock_item.get('exclude_bodies', []),
            'dimensions_mm': donor['overrides'],
            'source_files_sha256': {path.relative_to(ROOT).as_posix(): mesh.digest(path) for path in sorted(paths)}}


def native_pins(binding):
    return {**binding['source_files_sha256'], **{
        name: mesh.digest(ROOT / name) for name in (
            'scripts/build_lab3003_armc_variant_freecad.py', 'scripts/build_neutral_freecad.py',
            'scripts/export_building_walkthrough_freecad.py', 'scripts/freecad/solidcraftbot_freecad.py')}}


def read_native(report_path, binding):
    """Verify the arm geometry and mesh artifacts for exactly this bound variant."""
    path = Path(report_path).resolve()
    report = json.loads(path.read_text(encoding='utf-8'))
    if (report['format'] != NATIVE_FORMAT or report.get('passed') is not True
            or report['source_files_sha256'] != native_pins(binding)
            or any(report[key] != binding[key] for key in (
                'laboratory_id', 'device_id', 'dimensions_mm', 'park_joints_deg', 'body_prefix'))
            or not _pose_matches(report['bound_pose'], binding['bound_pose'])
            or not _pose_matches(report['world_pose'], binding['world_pose'])):
        raise ValueError('The native report does not certify the selected Lab 3.003 arm and placement')
    artifacts = {}
    for name, filename in (('freecad', 'ArmC-long.FCStd'), ('mesh', 'armc-native-mesh.json')):
        ref = report['artifacts'][name]
        artifact = path.parent / filename
        if ref['file'] != filename or artifact.is_symlink() or mesh.digest(artifact) != ref['sha256']:
            raise ValueError('The certified ArmC artifact changed: ' + filename)
        artifacts[name] = artifact
    return report, artifacts
