"""Publish a local docked ArmC playback only from passed native evidence."""

import argparse
import json
import math
from pathlib import Path

import build_building_walkthrough as browser
from build_lab3003_armc_preview import parked_payload
from build_lab3003_tr01_walkthrough import configure_cf01_cycle, read, replace_mesh
import centrifuge_robot_pickup as pickup
import export_building_walkthrough_freecad as mesh
import lab3003_cf01_cycle
from lab3003_tr01_return_lap import checked_lap
import robot_spec as robot


ROOT = browser.ROOT


def checked_transfer(program_path, proof_path, pusher_path, arm_path, stock_path, native):
    proof = read(proof_path)
    program = read(program_path)
    pusher = read(pusher_path)
    if (program.get('format') != 'solidcraftbot.lab3003-cf01-arm-program/1'
            or proof.get('format') != 'solidcraftbot.lab3003-cf01-transfer-collision/1'
            or proof.get('passed') is not True or proof.get('program_sha256') != mesh.digest(program_path)
            or proof.get('stock_html_sha256') != native['stock']['html_sha256']
            or pusher.get('format') != 'solidcraftbot.lab3003-cf01-pusher-geometry/1'
            or pusher.get('lowering_geometry_passed') is not True):
        raise ValueError('A complete native ArmC and pusher certificate for this exact dock setup is required')
    pins = proof['native_inputs_sha256']
    required = [arm_path, pusher_path, stock_path/'index.html', *native['native_paths'].values()]
    if any(pins.get(str(path.resolve())) != mesh.digest(path) for path in required):
        raise ValueError('The certified native scene, arm, or pusher geometry differs from this preview')
    for name, expected in pins.items():
        path = Path(name)
        if not path.is_absolute() or not path.is_file() or mesh.digest(path) != expected:
            raise ValueError('A native transfer input changed: '+name)
    mesh.verify_pins(program['source_files_sha256'])
    mesh.verify_pins(proof['source_files_sha256'])
    tracks, returns = program['samples'], program.get('return_samples')
    checked_tracks(tracks, proof['samples'])
    if returns is not None:
        if (proof.get('home_joints_deg') != program['home_joints_deg']
                or proof.get('parked_station_sweep', {}).get('passed') is not True):
            raise ValueError('The bent home must match the checked station sweep')
        checked_tracks(returns, proof['return_samples'])
    return tracks, returns, proof


def checked_tracks(tracks, certified):
    identity = lambda row: (row['id'], row['slot'])
    if (len(tracks) != 2 or [identity(item) for item in tracks] != [identity(item) for item in certified]
            or any(row.get('passed') is not True or not row.get('intervals') for row in certified)):
        raise ValueError('Both earlier and later carried tubes require independent whole-path evidence')
    for track, row in zip(tracks, certified):
        boundary = track['points'][0]['time_s']
        for interval in sorted(row['intervals'], key=lambda value: value['start_s']):
            start, end = interval['start_s'], interval['end_s']
            clearance = interval['clearance_lower_mm']
            if not (math.isclose(start, boundary, abs_tol=1e-9, rel_tol=0) and end > start
                    and math.isfinite(clearance) and clearance > 0):
                raise ValueError('The native certificate contains an uncovered or unsafe arm interval')
            boundary = end
        if not math.isclose(boundary, track['points'][-1]['time_s'], abs_tol=1e-9, rel_tol=0):
            raise ValueError('The native certificate must cover the entire arm motion')
        mesh.validate_rigid(row['raised_pose_from_cassette'])


def arm_config(lab, binding, scene):
    arm = binding['arm']
    parameters = robot.parameters(arm)
    fk = robot.forward(arm, binding['park_joints_deg'])
    joints = []
    for joint in arm['joints']:
        frame = robot.multiply(binding['world_pose'], robot.multiply(fk[joint['parent']], robot.frame(joint, parameters)))
        bodies = [group['id'] for group in scene['groups']
                  if group['id'].startswith(binding['body_prefix']) and group.get('rigid_link') == joint['child']]
        if not bodies:
            raise ValueError('The exact native arm must bind each moving link: '+joint['child'])
        joints.append({'origin_mm': [row[3] for row in frame[:3]],
                       'axis': [row[2] for row in frame[:3]], 'body_ids': bodies})
    return joints


def tool_mesh(lab, arm, gripper, reference_gap):
    # The shared primitive builder initializes FreeCAD before MeshPart loads.
    from build_synthetic_lab_scene_freecad import primitive
    import MeshPart

    base = arm['bound_pose']
    setup = {'arm_fixture': {'position_mm': [row[3] for row in base[:3]],
                             'yaw_deg': math.degrees(math.atan2(base[1][0], base[0][0]))},
             'gripper': gripper}
    kin = pickup.Kinematics(arm['arm'], setup)
    tcp = robot.multiply(lab['transform'], kin.tool(arm['park_joints_deg']))
    fingers = {'Tool': 0, 'FingerLeft': -.5, 'FingerRight': .5}
    builder = mesh.MeshBuilder()
    bodies = []
    for part in pickup.gripper_parts(setup, {}):
        factor = fingers[part['group']]
        frame = robot.multiply(tcp, pickup.placement([reference_gap*factor, 0, 0], 0))
        points, triangles, normals = mesh.native_face_mesh(primitive(part['shape']), 1., .35, MeshPart)
        ident = arm['body_prefix']+part['id']
        builder.add(ident, [mesh.rigid_point(frame, point) for point in points], triangles,
                    {'color': [.3, .38, .43], 'opacity': 1.}, level_id=lab['level_id'], role=part['role'],
                    instance_id=arm['device_id'], normals=[mesh.rigid_point(frame, v, vector=True) for v in normals])
        builder.groups[-1]['laboratory_id'] = lab['id']
        bodies.append({'id': ident, 'gap_axis': [factor * row[0] for row in tcp[:3]]})
    return builder.result(), {'reference_gap_mm': reference_gap, 'bodies': bodies}


def build(stock, arm_path, program_path, proof_path, pusher_path, output,
          *, lap_program=None, lap_report=None):
    payload, native = parked_payload(stock, arm_path)
    tracks, returns, proof = checked_transfer(program_path, proof_path, pusher_path, arm_path, stock, native)
    has_return = returns is not None
    if any((path is not None) != has_return for path in (lap_program, lap_report)):
        raise ValueError('The return cycle requires matching certified half-turn route inputs')
    lab = next(room for room in payload['laboratories'] if room['id'] == 'Lab3003')
    index_sweep = proof.get('open_lid_index_sweep')
    if index_sweep is not None and (not has_return or index_sweep.get('passed') is not True
            or index_sweep.get('lid_fixture_sweep', {}).get('passed') is not True
            or index_sweep.get('angle_interval_deg') != [-180., 0.]
            or index_sweep.get('seated_tube_id') != tracks[0]['id']
            or not math.isfinite(index_sweep['minimum_clearance_mm'])
            or index_sweep['minimum_clearance_mm'] <= 0.):
        raise ValueError('The open-lid index requires a positive native sweep with the first tube seated')
    cycle = lab3003_cf01_cycle.compile_cycle(
        arm_paths=tracks, return_paths=returns, keep_lid_open=index_sweep is not None)
    supports = {step['tube_id']: step['lift_mm'] for step in cycle['steps'] if step['phase'] == 'pusher_transfer'}
    if any(supports.get(row['id']) != row['lift_mm'] for row in proof['samples']):
        raise ValueError('The station trace differs from the certified support elevation')
    if returns is not None:
        raised = {step['tube_id']: step['lift_mm'] for step in cycle['steps'] if step['phase'] == 'pickup_raised'}
        if any(raised.get(row['id']) != row['lift_mm'] for row in proof['return_samples']):
            raise ValueError('The unloading trace differs from the certified support elevation')
    for sample in cycle['samples'] + cycle.get('return_samples', []):
        del sample['points'], sample['jaw_points']
    scene = payload['scenes']['building']
    arm = native['arm']
    joints = arm_config(lab, arm, scene)
    reference_gap = tracks[0]['jaw_points'][0]['positions_mm'][0]
    if not 0 < reference_gap <= proof['gripper']['open_gap_mm'] or any(
            not math.isclose(point['positions_mm'][0], reference_gap, abs_tol=1e-9, rel_tol=0)
            for track in tracks for point in (track['jaw_points'][0], track['jaw_points'][-1])):
        raise ValueError('Both jaw tracks must share the certified native park position')
    tool, tool_config = tool_mesh(lab, arm, proof['gripper'], reference_gap)
    scene = replace_mesh(scene, tool)
    scene['scope'] = 'Verified local docked ArmC transfers and CF01 pusher-supported seating'
    payload['scenes']['building'] = scene
    payload['isolation']['body_ids'] = sorted(set(payload['isolation']['body_ids']) |
                                              {group['id'] for group in tool['groups']})
    truck = native['stock_lap']
    configure_cf01_cycle(payload, lab, scene, cycle=cycle, truck=truck)
    cycle['arm_motion'] = {'samples': tracks, 'joints': joints, 'tool': tool_config,
                           'reference_deg': arm['park_joints_deg'],
                           'program_sha256': mesh.digest(program_path),
                           'collision_report_sha256': mesh.digest(proof_path),
                           'native_report_sha256': mesh.digest(arm_path)}
    cycle['arm_motion_checked'] = True
    cycle['docked_start'] = {key: truck[key] for key in ('level_id', 'fixture_states', 'parked_robots')}
    cycle['docked_start']['stop_id'] = payload['default_stop']
    if returns is not None:
        cycle['arm_motion'].update(return_samples=returns, home_deg=proof['home_joints_deg'])
        payload['tr01_lap'] = checked_lap(truck, lap_program, lap_report, stock, program_path)
        lap_pins = read(lap_report)['source_files_sha256']
        payload['source_files_sha256'] = browser.merge_pins(payload['source_files_sha256'], lap_pins)
    cycle['playback_rate'] = 4
    payload.pop('lab3003_armc_parked')
    payload['source_files_sha256'] = browser.merge_pins(payload['source_files_sha256'], proof['source_files_sha256'])
    mesh.verify_pins(payload['source_files_sha256'])
    output.mkdir(parents=True)
    html = output/'index.html'
    html.write_text(browser.embed_html(browser.TEMPLATE.read_text(), payload), encoding='utf-8')
    result = {'passed': True, 'scope': 'Native verified ArmC motion starting from the confirmed stationary dock.',
              'html_sha256': mesh.digest(html), 'arm_program_sha256': mesh.digest(program_path),
              'collision_report_sha256': mesh.digest(proof_path), 'pusher_geometry_report_sha256': mesh.digest(pusher_path),
              'browser_checked': False}
    if lap_report is not None:
        result['tr01_return_lap_report_sha256'] = mesh.digest(lap_report)
    (output/'preview-report.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stock-preview', 'armc-report', 'program', 'collision-report', 'pusher-report', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--lap-program', type=Path)
    parser.add_argument('--lap-report', type=Path)
    args = parser.parse_args()
    path = build(args.stock_preview, args.armc_report, args.program, args.collision_report,
                 args.pusher_report, mesh.project_path(args.output_dir),
                 lap_program=args.lap_program, lap_report=args.lap_report)
    print(path, flush=True)


if __name__ == '__main__':
    main()
