"""Compile and bind one covered TR01 lap with a half-turn at its existing stop."""

import argparse
import json
import math
from pathlib import Path

import assembly_model as assembly
from build_lab3003_armc_preview import checked_stock
import export_building_walkthrough_freecad as mesh
import tr01_floor_motion as tr01


SOURCE = tr01.ROOT / 'model/lab3003-tr01-return-lap.motion.json'
PROGRAM_FORMAT = 'solidcraftbot.lab3003-tr01-return-lap-program/1'
RECEIPT_FORMAT = 'solidcraftbot.lab3003-tr01-return-lap-native/1'
F = tr01.motion.FIELDS
AXES = ('linear', 'angular', 'carried_points')
LAYOUT_CLEARANCE_MM = 15.


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(path):
    return mesh.digest(Path(path))


def verify_reference(path, expected):
    if digest(path) != expected:
        raise ValueError('Changed TR01 lap reference: ' + str(path))


def checked_baseline(stock_path, certificate_path):
    payload, stock = checked_stock(Path(stock_path))
    verify_reference(certificate_path, stock['certificate_sha256'])
    cert = read(certificate_path)
    verify_reference(cert['motion_program']['file'], cert['motion_program']['sha256'])
    verify_reference(cert['native_model']['file'], cert['native_model']['sha256'])
    mesh.verify_pins(cert['source_files_sha256'])
    if (cert['passed'] is not True or cert['cover_on'] is not True
            or cert['floor_support']['passed'] is not True
            or cert['minimum_certified_clearance_mm'] < LAYOUT_CLEARANCE_MM
            or cert['native_collision_clearance']['passed'] is not True
            or cert['geometry_changes']['body_ids']
            or (cert['native_model'], cert['motion_program']) != (stock['native_model'], stock['motion_program'])):
        raise ValueError('The original covered TR01 lap and its native stock must be checked')
    baseline, = read(cert['motion_program']['file'])['routes']
    stock_route = payload['tr01_lap']
    if any(baseline[key] != stock_route[key] for key in ('points', 'duration_s', 'reversal', 'direction_sections')):
        raise ValueError('TR01 stock payload differs from the certified route')
    return payload, stock, cert, baseline


def _curve(points):
    # Analyze each section using its own clock and preserve the exported jets.
    # The absolute timestamps are removed only after float subtraction.
    return tr01.motion.Curve([{**row, 'time_s': row['time_s'] - points[0]['time_s']}
                              for row in points])


def _time_factor(bounds, limits):
    return max((value / limits[kind][name]) ** (1 / order)
               for kind in AXES
               for order, (name, value) in enumerate(bounds[kind].items(), 1))


def _stationary(point):
    return all(abs(value) <= 1e-9 for field in F[1:3] for value in point[field])


def _pivot_points(point, angle, limits, radius, quantum):
    endpoint = lambda t: {**point, 'time_s': t, F[0]: [*point[F[0]][:2], point[F[0]][2]+angle]}
    reference = _curve([point, endpoint(point['time_s']+1)])
    minimum = _time_factor(tr01.dynamics(reference, radius), limits)
    duration = math.ceil(minimum*(1+1e-6)/quantum)*quantum
    return endpoint(round((point['time_s']+duration)/quantum)*quantum)


def _sections(route, definition, radius):
    points = tr01.canonical(route['points'])
    sections = []
    for section in route['direction_sections']:
        selected = [row for row in points if section['start_s'] <= row['time_s'] <= section['end_s']]
        a, b = selected[0], selected[-1]
        if (a['time_s'] != section['start_s'] or b['time_s'] != section['end_s']
                or not _stationary(a) or not _stationary(b)):
            raise ValueError('A TR01 section must begin and end at its exact stationary knot')
        section_curve = _curve(selected)
        limits = tr01.dynamics(section_curve, radius)
        if _time_factor(limits, definition['limits']) > 1+1e-9:
            raise ValueError('TR01 section exceeds the source motion limits')
        proof = {'direction': section['direction'], 'dynamics': limits}
        if section['direction'] == 'pivot':
            if len(selected) != 2 or a[F[0]][:2] != b[F[0]][:2] or not math.isclose(
                    b[F[0]][2]-a[F[0]][2], math.pi, abs_tol=1e-9, rel_tol=0):
                raise ValueError('A single monotone stationary half-turn requires two exact knots')
            proof['stationary_center'] = True
            proof['monotone_yaw_rad'] = math.pi
        else:
            proof['no_stop_within_section'] = tr01.no_stop(section_curve)
            if not proof['no_stop_within_section']['passed']:
                raise ValueError('The covered translating route contains an internal stop')
        sections.append(proof)
    return sections


def compile_lap(stock_path, certificate_path):
    payload, stock, cert, baseline = checked_baseline(stock_path, certificate_path)
    config = read(SOURCE)
    if (config['format'] != 'solidcraftbot.lab3003-tr01-return-lap/1'
            or config['laboratory_id'] != payload['tr01_lap']['laboratory_id']
            or assembly.validate_reference(config['motion']) != tr01.SOURCE
            or config['pivot_deg'] != 180 or config['cover_required'] is not True
            or baseline['dock']['departure_mm_deg'][2] != config['old_dock_heading_deg']
            or [p['direction'] for p in cert['direction_checks']] != ['forward', 'reverse']
            or not all(p['longitudinal']['passed'] for p in cert['direction_checks'])):
        raise ValueError('The Lab 3.003 opposite-dock transfer needs the exact covered baseline')

    points = tr01.canonical(baseline['points'])
    stop_time = baseline['reversal']['time_s']
    pivot_idx, = (i for i, row in enumerate(points) if row['time_s'] == stop_time)
    before = points[:pivot_idx+1]
    stop = before[-1]
    first, last = points[0], points[-1]
    if (not all(_stationary(row) for row in (first, stop, last))
            or first[F[0]][:2] != last[F[0]][:2] or math.cos(last[F[0]][2]-first[F[0]][2]) < 1-1e-9):
        raise ValueError('Original route is not at rest at the two dock endpoints and the reversal')
    definition = tr01.load()
    quantum = definition['curve']['time_quantum_s']
    radius = max(p['dynamics']['radius_mm'] for p in baseline['direction_sections'])
    angle = math.radians(config['pivot_deg'])
    turn_end = _pivot_points(stop, angle, definition['limits'], radius, quantum)
    after = [{**row, 'time_s': round((row['time_s']+turn_end['time_s']-stop_time)/quantum)*quantum,
              F[0]: [*row[F[0]][:2], row[F[0]][2]+angle]} for row in points[pivot_idx+1:]]
    model_time = after[-1]['time_s']
    dock = dict(baseline['dock'], arrival_mm_deg=[*last[F[0]][:2], (config['old_dock_heading_deg']+180)%360])
    route = {
        'id': 'lab3003-cf01-return-opposite-dock',
        'points': tr01.public([*before, turn_end, *after]),
        'dock': dock,
        'duration_s': model_time,
        'approximate_length_mm': cert['length_mm'],
        'direction_sections': [
            {'direction': 'forward', 'start_s': 0., 'end_s': stop_time},
            {'direction': 'pivot', 'start_s': stop_time, 'end_s': turn_end['time_s']},
            {'direction': 'forward', 'start_s': turn_end['time_s'], 'end_s': model_time},
        ],
        'half_turn': {'start_s': stop_time, 'end_s': turn_end['time_s'], 'delta_rad': angle},
    }
    checks = _sections(route, definition, radius)
    checks[0]['longitudinal'] = {'passed': True, 'source': 'identical certified forward phase'}
    checks[-1]['longitudinal'] = {'passed': True,
        'source': 'certified reverse phase with an added constant pi yaw and shifted clock'}
    pins = dict(cert['source_files_sha256'])
    for path in (SOURCE, Path(__file__).resolve(), tr01.SOURCE, Path(tr01.__file__).resolve(),
                 Path(tr01.motion.__file__).resolve()):
        pins[str(path.relative_to(tr01.ROOT))] = digest(path)
    return {
        'format': PROGRAM_FORMAT,
        'definition': definition,
        'routes': [route],
        'section_checks': checks,
        'stock_html_sha256': stock['html_sha256'],
        'baseline_certificate_sha256': digest(certificate_path),
        'source_files_sha256': pins,
    }


def parked_arm(arm_program_path):
    """Read the exact arm and gripper state held throughout the covered lap."""
    arm = read(arm_program_path)
    home = arm['home_joints_deg']
    gap = arm['samples'][0]['jaw_points'][0]['positions_mm'][0]
    if len(home) != 6 or not arm['return_samples']:
        raise ValueError('A complete ArmC return to its checked driving fixture is required')
    for track in arm['return_samples']:
        end = track['points'][-1]
        jaw = track['jaw_points'][-1]
        if (not all(math.isclose(math.degrees(q), h, abs_tol=1e-7, rel_tol=0)
                    for q, h in zip(end['positions_rad'], home, strict=True))
                or not _stationary(end)
                or jaw['positions_mm'] != [gap]
                or jaw['velocities_mm_s'] != [0.] or jaw['accelerations_mm_s2'] != [0.]):
            raise ValueError('The returned tubes must leave ArmC and its jaws parked before driving')
    return home, gap


def checked_lap(config, program_path, receipt_path, stock_path, arm_program_path):
    """Apply an exactly checked half-turn route to the existing browser body binding."""
    program, receipt = read(program_path), read(receipt_path)
    home, gap = parked_arm(arm_program_path)
    route, = program['routes']
    if (program['format'] != PROGRAM_FORMAT or receipt['format'] != RECEIPT_FORMAT
            or receipt.get('passed') is not True
            or receipt['minimum_certified_clearance_mm'] < LAYOUT_CLEARANCE_MM
            or receipt['program_sha256'] != digest(program_path)
            or receipt['arm_program_sha256'] != digest(arm_program_path)
            or receipt['home_joints_deg'] != home
            or receipt['parked_jaw_gap_mm'] != gap
            or receipt['stock_html_sha256'] != program['stock_html_sha256']
            or receipt['stock_html_sha256'] != digest(Path(stock_path)/'index.html')
            or receipt['floor_support']['passed'] is not True
            or receipt['native_collision_clearance']['passed'] is not True
            or route['points'][0] != config['points'][0]
            or config['cover_body_id'] not in config['body_ids']):
        raise ValueError('The covered half-turn needs its exact passing native evidence')
    mesh.verify_pins(program['source_files_sha256'])
    mesh.verify_pins(receipt['source_files_sha256'])
    for path, sha in receipt['native_inputs_sha256'].items():
        verify_reference(path, sha)
    result = {key: value for key, value in config.items() if key != 'reversal'}
    return {**result, **{key: route[key] for key in ('points', 'duration_s', 'direction_sections', 'half_turn')},
            'autoplay': False, 'minimum_clearance_mm': receipt['minimum_certified_clearance_mm'],
            'route_certificate_sha256': digest(receipt_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-preview', required=True, type=Path)
    parser.add_argument('--baseline-certificate', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    program = compile_lap(args.stock_preview, args.baseline_certificate)
    write(args.out, program)
    print(args.out)


if __name__ == '__main__':
    main()
