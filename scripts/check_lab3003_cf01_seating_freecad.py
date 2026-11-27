"""Check a geometric pusher-supported load in the indexed CF01 concept."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import FreeCAD as App
import Part

import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import lab_layout_model as layout
import robot_spec as robot
import tr01_workcell as workcell

sys.path.insert(0, str(Path(__file__).resolve().parent/'freecad'))
from build_centrifuge_freecad import set_pose
from solidcraftbot_freecad import features, world_shape

VOLUME_EPS_MM3 = 0.0001
LATERAL_ESCAPE_MM = 12.
AXIAL_ESCAPE_MM = 24.
SAMPLES = (('B2_Tube01', 1), ('B2_Tube07', 7))
IGNORE_ROLES = {'illustrative_tube', 'closed_cap_envelope', 'surface_marking_visual_only'}


def overlaps(shape, obstacles):
    hits = {}
    bounds = shape.BoundBox
    for name, obstacle in obstacles.items():
        if bounds.intersect(obstacle.BoundBox):
            volume = shape.common(obstacle).Volume
            if volume > VOLUME_EPS_MM3:
                hits[name] = volume
    return hits


def moved(shape, transform):
    result = shape.copy()
    result.Placement = transform.multiply(result.Placement)
    return result


def shape_error(a, b):
    overlap = a.common(b).Volume
    return max(0., a.Volume+b.Volume-2*overlap)


def prepared_vehicle(path):
    source = layout.load(validate_builds=False)
    vehicle = next(item for item in source['instances'] if item['id'] == 'TR01')
    provider = layout.provider(vehicle['asset'])
    spec = layout.instance_source(source, vehicle)
    parameters = provider.parameters(spec)
    expanded = provider.expanded(spec, parameters, layout.instance_variant(spec, vehicle))
    document = App.openDocument(str(path))
    try:
        shapes = {obj.SourceBody: world_shape(obj) for obj in features(document)}
        data = {}
        for identity, _ in SAMPLES:
            recipes = [item['shape'] for item in expanded['operations'] if item['body'] == identity]
            if any(item['kind'] != 'cylinder' or item['axis'] != [0, 0, 1] for item in recipes):
                raise ValueError('A coaxial cylindrical cassette shaft and cap are required')
            rebuilt = Part.makeCylinder(recipes[0]['radius'], recipes[0]['height'],
                                        App.Vector(*recipes[0]['origin']))
            for recipe in recipes[1:]:
                rebuilt = rebuilt.fuse(Part.makeCylinder(recipe['radius'], recipe['height'],
                                                         App.Vector(*recipe['origin'])))
            if shape_error(rebuilt, shapes[identity]) > VOLUME_EPS_MM3:
                raise ValueError('TR01 native solid differs from its source cylinders: '+identity)
            geometry = workcell.tube_geometry(expanded, identity,
                json.loads(workcell.SOURCE.read_text())['cargo_grip_offset_from_top_mm'])
            bottom = App.Vector(*recipes[0]['origin'])
            data[identity] = (shapes[identity], recipes, bottom, geometry['grip_mm'][2]-bottom.z)
    finally:
        App.closeDocument(document.Name)
    return data


def pocket(station, parameters, slot, rotor, height=0.):
    bottom, axis = cf.pocket(station, parameters, slot)
    turn = App.Rotation(App.Vector(0, 0, 1), rotor)
    axis = turn.multVec(App.Vector(*axis))
    return turn.multVec(App.Vector(*bottom))+axis*height, axis


def vessel_at(vessel, bottom, axis):
    shape, _, origin, _ = vessel
    rotation = App.Rotation(App.Vector(0, 0, 1), axis)
    return moved(shape, App.Placement(bottom-rotation.multVec(origin), rotation))


def shaft_and_cap_sweep(vessel, bottom, axis, travel):
    _, recipes, origin, _ = vessel
    rotation = App.Rotation(App.Vector(0, 0, 1), axis)
    swept = []
    for recipe in recipes:
        start = bottom + rotation.multVec(App.Vector(*recipe['origin'])-origin)
        swept.append(Part.makeCylinder(recipe['radius'], recipe['height']+travel, start, axis))
    return swept


def rotational_tool_frame(grip, axis, tilt, roll):
    frame = pickup.tool_target(list(grip), tilt, roll)
    if max(abs(frame[i][2]+axis[i]) for i in range(3)) > 1e-7:
        raise ValueError('The indexed pocket axis differs from the gripper axis')
    return App.Placement(App.Matrix(*[value for row in frame for value in row]))


def tool_envelopes(parts, frame, gap_a, gap_b, lateral_y=0., axial_withdrawal=0.):
    # Exact box sweep for each stem and pad. The cylinder at the flange is
    # replaced by its conservative enclosing box only during lateral travel.
    for part in parts:
        shape = part['shape']
        factor = {'FingerLeft': -.5, 'FingerRight': .5, 'Tool': 0.}[part['group']]
        x, y, z = shape['origin']
        shift_a, shift_b = factor*gap_a, factor*gap_b
        x += min(shift_a, shift_b)
        y += min(0., lateral_y)
        z -= axial_withdrawal
        if shape['kind'] == 'box':
            dx, dy, dz = shape['size']
            solid = Part.makeBox(dx+abs(shift_b-shift_a), dy+abs(lateral_y), dz+axial_withdrawal,
                                 App.Vector(x, y, z))
        elif lateral_y:
            radius = shape['radius']
            solid = Part.makeBox(2*radius, 2*radius+abs(lateral_y), shape['height'],
                                 App.Vector(x-radius, y-radius, z))
        else:
            solid = Part.makeCylinder(shape['radius'], shape['height']+axial_withdrawal,
                                      App.Vector(x, y, z))
        yield part['id'], moved(solid, frame)


def screen_release(parts, grip, axis, tilt, gap_closed, gap_open, obstacles, axial=False):
    failures = Counter()
    witness = None
    checked = 0
    for roll in (*range(0, 180, 15), *range(-15, -181, -15)):
        frame = rotational_tool_frame(grip, axis, tilt, roll)
        jaw_open = [(name, hits) for name, solid in tool_envelopes(parts, frame, gap_closed, gap_open)
                    if (hits := overlaps(solid, obstacles))]
        checked += 1
        if jaw_open:
            failures.update((part, obstacle) for part, hits in jaw_open for obstacle in hits)
            continue
        escapes = [{'axial_withdrawal': AXIAL_ESCAPE_MM}] if axial else [
            {'lateral_y': direction*LATERAL_ESCAPE_MM} for direction in (-1, 1)]
        for escape in escapes:
            clean = True
            for part, solid in tool_envelopes(parts, frame, gap_open, gap_open, **escape):
                hits = overlaps(solid, obstacles)
                if hits:
                    clean = False
                    failures.update((part, obstacle) for obstacle in hits)
            if clean:
                witness = {'roll_deg': roll, 'escape': escape,
                           'closed_gap_mm': gap_closed, 'open_gap_mm': gap_open}
                break
        if witness is not None:
            break
    return {'candidate_found': witness is not None, 'rolls_checked': checked, 'witness': witness,
            'blocked_pairs': [{'gripper_part': part, 'obstacle': obstacle, 'count': count}
                              for (part, obstacle), count in failures.items()]}


def check(vehicle_path, station_path, expected):
    if not all(expected.get(str(path)) == robot.digest(path) for path in (vehicle_path, station_path)):
        raise ValueError('Native inputs must match the independent rotor-fit evidence')
    vehicle = prepared_vehicle(vehicle_path)
    station = cf.load()
    parameters = cf.parameters(station)
    expanded = cf.expanded(station, parameters)
    pusher = next(item['shape'] for item in expanded['operations'] if item['body'] == 'RetractablePusher')
    stroke = parameters['lift_travel']
    park_gap = parameters['park_gap']
    model = pickup.load()
    gap_station = model['gripper']['open_gap_mm']
    model['gripper'].update(json.loads(workcell.SOURCE.read_text())['gripper_overrides'])
    parts = pickup.gripper_parts(model, {})
    gap_open = model['gripper']['open_gap_mm']
    doc = App.openDocument(str(station_path))
    reports = []
    try:
        for index, (identity, slot) in enumerate(SAMPLES):
            rotor = -(slot-1)*360./station['rotor']['slots']
            set_pose(doc, expanded, {**cf.pose(station, parameters, 'open'), 'Rotor': rotor,
                                   'Lift': park_gap+stroke, 'TubeLift': 0.})
            objects = {obj.SourceBody: obj for obj in features(doc)}
            fixed = {name: world_shape(obj) for name, obj in objects.items()
                     if obj.ModelRole not in IGNORE_ROLES and name != 'RetractablePusher'}
            for other, other_slot in SAMPLES[:index]:
                other_bottom, other_axis = pocket(station, parameters, other_slot, rotor)
                fixed['Seated.'+other] = vessel_at(vehicle[other], other_bottom, other_axis)
            bottom, axis = pocket(station, parameters, slot, rotor)
            raised_bottom = bottom+axis*stroke
            raised_tube = vessel_at(vehicle[identity], raised_bottom, axis)
            seated_tube = vessel_at(vehicle[identity], bottom, axis)
            raised_pusher = world_shape(objects['RetractablePusher'])
            expected_pusher = Part.makeCylinder(pusher['radius'], pusher['height'],
                                                raised_bottom-axis*pusher['height'], axis)
            pusher_error = shape_error(raised_pusher, expected_pusher)
            contact_gap = raised_pusher.distToShape(raised_tube)[0]
            contact_overlap = raised_pusher.common(raised_tube).Volume
            if pusher_error > VOLUME_EPS_MM3 or contact_gap > 1e-6 or contact_overlap > VOLUME_EPS_MM3:
                raise ValueError('Raised pusher does not meet the exact indexed tube support face')

            tube_hits = [overlaps(shape, fixed) for shape in
                         shaft_and_cap_sweep(vehicle[identity], bottom, axis, stroke)]
            parked_start = bottom-axis*(pusher['height']+park_gap)
            pusher_sweep = Part.makeCylinder(pusher['radius'], pusher['height']+park_gap+stroke,
                                             parked_start, axis)
            pusher_hits = overlaps(pusher_sweep, fixed)
            retract = Part.makeCylinder(pusher['radius'], pusher['height']+park_gap, parked_start, axis)
            retract_hits = overlaps(retract, {'Seated.'+identity: seated_tube})
            grip = raised_bottom+axis*vehicle[identity][3]
            release_obstacles = {**fixed, 'RaisedPusher': raised_pusher, 'Supported.'+identity: raised_tube}
            tilt = station['rotor']['tilt_from_vertical_deg']
            gap_closed = 2*vehicle[identity][1][0]['radius']
            lateral_release = screen_release(parts, grip, axis, tilt, gap_closed, gap_open, release_obstacles)
            axial_release = screen_release(parts, grip, axis, tilt, gap_closed, gap_station, release_obstacles,
                                           axial=True)

            row = {'id': identity, 'slot': slot, 'rotor_deg': rotor, 'support_height_mm': stroke,
                   'support_shape_error_mm3': pusher_error, 'support_gap_mm': contact_gap,
                   'support_overlap_mm3': contact_overlap,
                   'geometric_contact_area_mm2': math.pi*pusher['radius']**2,
                   'lowering_tube_overlaps_mm3': tube_hits, 'pusher_sweep_overlaps_mm3': pusher_hits,
                   'pusher_retraction_overlaps_mm3': retract_hits,
                   'lowering_clear': not any(tube_hits) and not pusher_hits and not retract_hits,
                   'raised_lateral_release': lateral_release, 'raised_axial_release': axial_release}
            reports.append(row)
            print(json.dumps(row), flush=True)
    finally:
        App.closeDocument(doc.Name)
    return {'format': 'solidcraftbot.lab3003-cf01-pusher-geometry/1',
            'samples': reports, 'native_inputs_sha256': expected,
            'source_files_sha256': {str(path.relative_to(cf.ROOT)): robot.digest(path)
                for path in (Path(__file__).resolve(), cf.SOURCE, layout.SOURCE, pickup.SOURCE, workcell.SOURCE)},
            'lowering_geometry_passed': all(row['lowering_clear'] for row in reports),
            'local_tool_escape_found': all(row['raised_lateral_release']['candidate_found'] or
                                           row['raised_axial_release']['candidate_found'] for row in reports),
            'empty_pocket_pusher_protocol_available': False,
            'arm_trajectory_checked': False,
            'scope': 'Unmodified cassette solids. Exact native axial sweeps include the installed pusher and '
                     'prior delivered tube. The coaxial planar support contact supplies no evidence of '
                     'retention, stability, instrument qualification, or real operation. Local jaw and exit '
                     'sweeps do not establish ArmC reach, fixture clearance, or a transfer path.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vehicle', type=Path, required=True)
    parser.add_argument('--station', type=Path, required=True)
    parser.add_argument('--input-proof', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    pins = json.loads(args.input_proof.read_text())['checked_native_shas']
    report = check(args.vehicle.resolve(), args.station.resolve(), pins)
    args.out.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
