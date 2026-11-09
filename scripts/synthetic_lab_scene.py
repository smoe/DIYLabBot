"""Compose instrument instances with the existing CF01 scene; no new geometry."""
import copy
import math
import re

import assembly_model as assembly
import instrument_concept as instruments
import robot_spec as robot
import synthetic_workspace as workspace

ROOT = robot.ROOT
INSTRUMENT_ASSETS = {'nanodrop': 'nanodrop-concept', 'qubit': 'qubit-4-concept'}


def verify_core_geometry(report, scene, trajectory, poses):
    """Prove that a changed composition still produces the same core geometry.

    Only composition references may differ. Original artifact checksums and the
    rest of the source manifest are checked by the caller. No historical report
    or checksum is rewritten to describe the new layout.
    """
    import centrifuge_pickup_solidcraft as native
    import robot_components
    library = robot_components.library(__import__('centrifuge_robot_pickup').arm_source(scene))
    sections = {str(ROOT/library['parts'][part['part']]['sections']['housing']['step']): part['output']
                for part in report['vendor_exterior']['parts']}
    current, manifest = native.construction(scene, sections)
    command_path = next(ROOT/p for p in report['artifact_sha256'] if p.endswith('/native-base.commands.json'))
    previous = __import__('json').loads(command_path.read_text())['commands']
    if current != previous or manifest != report['body_manifest']:
        raise ValueError('Core construction changed; regenerate the independent CF01 scene')

    def equal(a, b):
        if type(a) in (int, float) and type(b) in (int, float):
            return math.isclose(a, b, abs_tol=1e-8, rel_tol=1e-12)
        if isinstance(a, dict) and isinstance(b, dict):
            return set(a) == set(b) and all(equal(a[k], b[k]) for k in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        return a == b
    for phase, time_s in poses:
        path = next(ROOT/p for p in report['artifact_sha256'] if p.endswith('/'+phase+'.solidcraft.commands.json'))
        old = [c for c in __import__('json').loads(path.read_text())['commands'] if c['command'] != 'document.metadata.set']
        commands, _ = native.placements(scene, trajectory, time_s)
        if not equal(commands, old):
            raise ValueError('Core pose changed; regenerate the independent CF01 scene')
    return {'passed': True, 'method': 'Exact equality of construction commands and body manifest; pose matrices equal within 1e-8 mm numerical tolerance',
            'construction_commands': str(command_path.relative_to(ROOT)),
            'construction_commands_sha256': robot.digest(command_path)}


def instrument_instances(spatial=None):
    spatial = spatial or workspace.load()
    result = []
    for item in spatial['devices'].values():
        if item['asset'] not in INSTRUMENT_ASSETS:
            continue
        spec = assembly.load_instance(instruments, item['source'], item.get('overrides'))
        if spec['family'] != INSTRUMENT_ASSETS[item['asset']]:
            raise ValueError('Instrument source does not match instance asset: ' + item['id'])
        result.append({'instance': item, 'spec': spec, 'parameters': instruments.parameters(spec)})
    if {i['instance']['asset'] for i in result} != set(INSTRUMENT_ASSETS):
        raise ValueError('Complete scene requires NanoDrop and Qubit instances')
    return result


def component_matrix(entry, component, angle=None):
    p, spec = entry['parameters'], entry['spec']
    angle = instruments.pose(spec, p)['Hinge'] if angle is None else angle
    origin = instruments.transform(spec, p, component, [0, 0, 0], angle)
    basis = [instruments.transform(spec, p, component, point, angle)
             for point in ([1, 0, 0], [0, 1, 0], [0, 0, 1])]
    local = [[basis[j][i]-origin[i] for j in range(3)]+[origin[i]]
             for i in range(3)] + [[0, 0, 0, 1]]
    return robot.multiply(entry['instance']['matrix'], local)


def instrument_reachability(scene, entries, approach_height_mm=150):
    """Derive vertical reference-TCP targets from each instrument interface.

    Surface reach is kinematic only. The existing illustrative tube gripper is
    a TCP datum, not a NanoDrop pipette or a qualified Qubit loading tool.
    Approach configurations receive separate native BRep checks in the build.
    """
    import centrifuge_robot_pickup as pickup
    kin = pickup.Kinematics(pickup.arm_source(scene), scene)
    checks = []
    for entry in entries:
        surface = robot.transform(entry['instance']['matrix'],
                                  instruments.interfaces(entry['spec'], entry['parameters'])['sample_surface'])
        seed = scene['ik_seed_deg']
        for kind, height in [('surface', 0), ('approach', approach_height_mm)]:
            point = [surface[0], surface[1], surface[2]+height]
            target = pickup.tool_target(point, 0)
            seed = kin.inverse(target, seed)
            error = kin.residual(seed, target)
            position_error = math.sqrt(sum(e*e for e in error[:3]))
            orientation_error = math.degrees(math.sqrt(sum(e*e for e in error[3:]))/100)
            within_limits = all(lo <= q <= hi for q, (lo, hi) in zip(seed, kin.limits))
            checks.append({'id': entry['instance']['id']+'.'+kind, 'instance': entry['instance']['id'],
                           'kind': kind, 'surface_world_mm': surface, 'height_above_surface_mm': height,
                           'target_matrix': target, 'joints_deg': seed[:],
                           'position_error_mm': position_error, 'orientation_error_deg': orientation_error,
                           'within_joint_limits': within_limits,
                           'passed': within_limits and position_error < 0.01 and orientation_error < 0.01})
    return {'passed': all(c['passed'] for c in checks), 'checks': checks,
            'joint_limits_deg': kin.limits, 'approach_height_mm': approach_height_mm,
            'reference_tcp': {'source': str(pickup.SOURCE.relative_to(ROOT)),
                              'flange_to_grip_mm': kin.length,
                              'orientation': 'Vertical, TCP Z points down; world X direction fixed'},
            'scope': 'Static reference-TCP reach at the source-defined sample interface and above it; no measurement tool or connecting trajectory'}


def frozen_commands(entry):
    """Namespace the existing adapter and freeze its source-selected hinge pose.

    A frozen review scene does not expose live instrument joints. The native
    standalone models remain the editable, independently generated assemblies.
    """
    spec, p = entry['spec'], entry['parameters']
    expanded = instruments.expanded(spec, p)
    prefix = re.sub(r'[^A-Za-z0-9_]', '_', entry['instance']['id']) + '_'
    names = set(spec['parameters'])
    names.update(b['id'] for b in expanded['bodies'])
    names.update(c['id'] for c in expanded['components'])
    names.update(o['id'] for o in expanded['operations'])
    names.update(o['id']+'_Sketch' for o in expanded['operations'])
    mapping = {name: prefix+name for name in names}
    parameter_pattern = re.compile(r'\b('+'|'.join(map(re.escape, spec['parameters']))+r')\b')

    def rename(value):
        if isinstance(value, str):
            return mapping[value] if value in mapping else parameter_pattern.sub(lambda m: mapping[m[0]], value)
        if isinstance(value, list):
            return [rename(v) for v in value]
        if isinstance(value, dict):
            return {k: rename(v) for k, v in value.items()}
        return value

    commands = []
    for original in instruments.solidcraft_commands(spec, p):
        command = original['command']
        if command.startswith('joint.') or command == 'document.metadata.set':
            continue
        item = rename(copy.deepcopy(original))
        if command == 'component.create':
            item['params']['grounded'] = True
        commands.append(item)
    for component in expanded['components']:
        commands.append({'command': 'occurrence.move', 'params': {
            'occurrence': mapping[component['id']]+':1', 'space': 'world',
            'matrix': component_matrix(entry, component['id']), 'move_grounded': True}})
    manifest = [{'instance': entry['instance']['id'], 'source_body': b['id'],
                 'names': [mapping[b['id']]], 'role': b['role']}
                for b in expanded['bodies']]
    return commands, manifest


def instance_metrics(bodies):
    volume = sum(b['volume_mm3'] for b in bodies)
    if volume <= 0 or not all(b.get('closed', True) for b in bodies):
        raise ValueError('Closed, positive scene bodies required')
    return {'body_count': len(bodies), 'volume_mm3': volume,
            'center_of_mass_mm': [sum(b['volume_mm3']*b['center_of_mass'][i] for b in bodies)/volume for i in range(3)],
            'bbox': {key: [(min if key == 'min' else max)(b['bbox'][key][i] for b in bodies)
                          for i in range(3)] for key in ('min', 'max')}}


def compare_instances(solidcraft, freecad, manifest):
    known = {b['name']: b for b in solidcraft['bodies']}
    if set(known) != {n for b in manifest for n in b['names']}:
        raise ValueError('Composed scene body identity mismatch')
    results = []
    for identity, expected in freecad['instance_metrics'].items():
        names = [n for b in manifest if b['instance'] == identity for n in b['names']]
        actual = instance_metrics([known[n] for n in names])
        volume_error = abs(actual['volume_mm3']-expected['volume_mm3'])/expected['volume_mm3']
        center_error = math.dist(actual['center_of_mass_mm'], expected['center_of_mass_mm'])
        results.append({'instance': identity, 'relative_volume_error': volume_error,
                        'center_error_mm': center_error,
                        'freecad_body_count': expected['body_count'], 'solidcraft_body_count': actual['body_count'],
                        'passed': volume_error < 0.001 and center_error < 0.02})
    return results
