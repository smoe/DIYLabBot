"""Derive the Lab 3.003 dock-to-raised-pusher PVA channels from their sources."""

import argparse
import itertools
import json
import math
from pathlib import Path

import assembly_model
import build_lab3003_armc_preview as preview
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import lab3003_armc_variant as variant
import lab3003_cf01_cycle as cycle
import lab_layout_model as layout
import lab_transfer_model as transfer
import robot_spec as robot
import tr01_workcell as workcell
from cf01_unload_motion import carried_bounds, load as load_limits, _sample_factor
from cf01_unload_path import CornerPath
from cf01_unload_validation import no_stop
from sample_motion import KinematicJets, motion

ROOT = robot.ROOT
SOURCE = ROOT / 'model/lab3003-cf01-arm-route.motion.json'
FORMAT = 'solidcraftbot.lab3003-cf01-arm-program/1'
POSITION, VELOCITY, ACCELERATION, JERK = motion.FIELDS
JAW_FIELDS = ('positions_mm', 'velocities_mm_s', 'accelerations_mm_s2')


def vector_at(a, b, progress):
    return [start + progress * (end - start) for start, end in zip(a, b)]


def joint_blend(start, end, offsets, progress):
    return [value + 2. * progress * (1. - progress) * offset
            for value, offset in zip(vector_at(start, end, progress), offsets)]


def point(time_s, position, fields=motion.FIELDS):
    return {'time_s': time_s, **dict(zip(fields, (position, [0.] * len(position), [0.] * len(position))))}


def pose(xyz, tilt, roll, yaw=0.):
    frame = robot.multiply(pickup.placement([0., 0., 0.], yaw), pickup.tool_target(xyz, tilt, roll))
    for axis, value in enumerate(xyz):
        frame[axis][3] = value
    return frame


def smooth_clock(nodes):
    """Reparameterize the joint path without forcing transit waypoints to rest."""
    start = nodes[0][0]
    times = [time - start for time, _ in nodes]
    angles = [[math.radians(v) for v in joints] for _, joints in nodes]
    shape = motion.Curve(motion.from_positions(times, angles, rest_endpoints=False))
    duration = times[-1]
    result = [point(0., angles[0])]
    for travel_time in times[1:-1]:
        fraction = travel_time / duration
        lo, hi = 0., 1.
        for _ in range(55):
            middle = (lo + hi) / 2.
            if motion.septic(middle) < fraction:
                lo = middle
            else:
                hi = middle
        phase = (lo + hi) / 2.
        rate = motion.septic(phase, 1)
        acceleration = motion.septic(phase, 2) / duration
        state = shape.evaluate(travel_time)
        result.append({
            'time_s': duration * phase,
            POSITION: state[POSITION],
            VELOCITY: [rate * speed for speed in state[VELOCITY]],
            ACCELERATION: [rate**2 * second + acceleration * speed
                           for speed, second in zip(state[VELOCITY], state[ACCELERATION])],
        })
    result.append(point(duration, angles[-1]))
    return result


def chord_clock(nodes):
    """Give equally sized joint-space steps comparable travel time."""
    elapsed = 0.
    result = [(elapsed, nodes[0][1])]
    for (_, before), (_, after) in zip(nodes, nodes[1:]):
        elapsed += math.dist(before, after)
        result.append((elapsed, after))
    return result


def reversed_handoff(track):
    """Reverse the articulated curve and confirm custody after the jaw travel."""
    duration = track['points'][-1]['time_s']

    def reverse(points, velocity):
        return [{**node, 'time_s': duration - node['time_s'],
                 velocity: [-value for value in node[velocity]]} for node in reversed(points)]

    jaw = track['jaw_points']
    return {'id': track['id'], 'slot': track['slot'], 'direction': 'unload',
            'points': reverse(track['points'], VELOCITY),
            'jaw_points': reverse(jaw, JAW_FIELDS[1]),
            'grip_s': duration - jaw[3]['time_s'], 'seat_s': duration - jaw[1]['time_s']}


class Workspace:
    def __init__(self, stock_preview):
        self.route = preview.read(SOURCE)
        if self.route['format'] != 'solidcraftbot.lab3003-cf01-arm-route/1':
            raise ValueError('Lab 3.003 arm route source required')
        paths = {name: assembly_model.validate_reference(ref) for name, ref in self.route['sources'].items()}
        if paths != {'variant': variant.SOURCE, 'cycle': cycle.SOURCE, 'gripper': pickup.SOURCE,
                     'motion_limits': ROOT / 'model/cf01-unload-demo.motion.json', 'cassette_grasp': workcell.SOURCE}:
            raise ValueError('Pinned Lab 3.003 route sources are required')
        payload, stock = preview.checked_stock(stock_preview)
        lab, = [room for room in payload['laboratories'] if room['id'] == 'Lab3003']
        arm = variant.bind(lab)
        self.stock_sha256 = stock['html_sha256']
        self.park = self.route['home_joints_deg']
        self.device = {item['id']: item['bound_pose'] for item in lab['device_instances']}
        self.cassette = preview.read(paths['cassette_grasp'])
        self.motion = load_limits(paths['motion_limits'])
        self.samples = cycle._load_source()[0]['samples']
        source = layout.load(validate_builds=False)
        items = {item['id']: item for item in source['instances']}
        vehicle = items['TR01']
        provider = layout.provider(vehicle['asset'])
        construction = layout.instance_source(source, vehicle)
        self.cargo = provider.expanded(construction, provider.parameters(construction),
                                       layout.instance_variant(construction, vehicle))
        self.station = layout.instance_source(source, items['CF01'])
        self.cp = cf.parameters(self.station)
        scene = pickup.load()
        base = arm['bound_pose']
        scene['arm_fixture'].update(position_mm=[row[3] for row in base[:3]],
                                    yaw_deg=math.degrees(math.atan2(base[1][0], base[0][0])))
        self.kin = pickup.Kinematics(arm['arm'], scene)
        if (not isinstance(self.park, list) or len(self.park) != len(self.kin.limits)
                or not all(type(value) in (float, int) and low <= value <= high
                           for value, (low, high) in zip(self.park, self.kin.limits))):
            raise ValueError('The runtime home must specify six finite, in-range arm angles')
        self.jets = KinematicJets(self.kin)
        self.gripper = scene['gripper']
        self.ik = {'arm': arm['arm'], 'ap': self.kin.p, 'base': base}
        self.tool = {'tool': {'flange_standoff_mm': self.kin.length},
                     'checks': {'tcp_error_mm': 1.e-5, 'axis_error_deg': .001}}
        self.pins = dict(arm['source_files_sha256'])
        for path in (SOURCE, Path(__file__), *paths.values(), cf.SOURCE,
                     ROOT / source['assets']['transporter']['source'],
                     Path(transfer.__file__), Path(motion.__file__)):
            self.pins[str(path.relative_to(ROOT))] = robot.digest(path)

    def inverse(self, target, previous=None):
        xyz = [row[3] for row in target[:3]]
        axis = [-row[2] for row in target[:3]]
        tool_x = [row[0] for row in target[:3]]
        solutions = []
        for candidate in transfer.oriented_solutions(self.ik, self.tool, xyz, axis):
            joints = candidate['q'][:]
            if joints[2] > 0:
                continue
            frame = self.kin.tool(joints)
            x = math.fsum(row[0] * value for row, value in zip(frame, tool_x))
            y = math.fsum(row[1] * value for row, value in zip(frame, tool_x))
            joints[-1] = (joints[-1] + math.degrees(math.atan2(y, x)) + 180.) % 360. - 180.
            lo, hi = self.kin.limits[-1]
            if lo <= joints[-1] <= hi and math.hypot(*self.kin.residual(joints, target)) < 1.e-5:
                solutions.append(joints)
        if not solutions:
            raise ValueError(f'Unreachable transfer reference at {xyz}')
        joints = min(solutions, key=lambda q: math.dist(q, self.park if previous is None else previous))
        if previous is not None and math.dist(joints, previous) > 25.:
            raise ValueError(f'IK branch jump at {xyz}')
        return joints

    def leg(self, reference, count, start, end, seed=None):
        nodes = []
        for index in range(count + 1):
            progress = index / count
            seed = self.inverse(reference(progress), seed)
            nodes.append((start + (end - start) * progress, seed))
        return nodes

    def fit(self, nodes, sample_points=()):
        points = smooth_clock(chord_clock(nodes)) if len(nodes) > 2 else [
            point(0., [math.radians(v) for v in nodes[0][1]]),
            point(nodes[-1][0] - nodes[0][0], [math.radians(v) for v in nodes[-1][1]]),
        ]
        bounds = motion.bounds(points)
        if any(lo < math.radians(low) - 1.e-7 or hi > math.radians(high) + 1.e-7
               for lo, hi, (low, high) in zip(bounds[POSITION]['min'], bounds[POSITION]['max'], self.kin.limits)):
            raise ValueError('Fitted arm curve exceeds a joint position limit')
        limits = self.motion['limits']
        caps = limits['arm_loaded' if sample_points else 'arm_empty']
        factor = max((max(bounds[field]['max_abs']) / caps[key]) ** (1 / order)
                     for order, (field, key) in enumerate(zip((VELOCITY, ACCELERATION, JERK),
                         ('velocity_rad_s', 'acceleration_rad_s2', 'jerk_rad_s3')), 1))
        evidence = {}
        if sample_points:
            bounds = carried_bounds(self.jets, points, sample_points, self.motion)
            factor = max(factor, _sample_factor(bounds, limits))
            evidence['sample_bounds_before_time_scaling'] = bounds
        factor = max(factor, .01) * 1.00001
        timed = motion.scale(points, factor)
        if sample_points:
            evidence['no_stop'] = no_stop(motion.Curve(timed), 0., timed[-1]['time_s'], self.jets, sample_points,
                                          {'stop_joint_speed_rad_s': 1.e-6, 'stop_speed_mm_s': .01})
            if not evidence['no_stop']['passed']:
                raise ValueError('A loaded waypoint forced a stop')
        evidence['applied_time_scale'] = factor
        evidence['joint_bounds'] = motion.bounds(timed)
        curve = motion.Curve(timed)
        xyz = []
        for t0, t1 in zip(curve.times, curve.times[1:]):
            for index in range(8):
                q = curve.evaluate(t0 + (t1 - t0) * index / 8)[POSITION]
                xyz.append([row[3] for row in self.kin.tool([math.degrees(v) for v in q])[:3]])
        xyz.append([row[3] for row in self.kin.tool([math.degrees(v) for v in timed[-1][POSITION]])[:3]])
        evidence['sampled_tcp_path_mm'] = sum(math.dist(a, b) for a, b in zip(xyz, xyz[1:]))
        evidence['tcp_endpoint_distance_mm'] = math.dist(xyz[0], xyz[-1])
        evidence['duration_s'] = timed[-1]['time_s']
        return timed, evidence

    def track(self, sample):
        identity, slot = sample['id'], sample['slot']
        approach = self.route['cassette_approach']
        station_entry = self.route['station_approach']
        geometry = workcell.tube_geometry(self.cargo, identity, self.cassette['cargo_grip_offset_from_top_mm'])
        grip_adjustment = approach['grip_adjustment_mm']
        geometry['grip_mm'][2] += grip_adjustment
        geometry['tool_axial_bounds_mm'] = [value + grip_adjustment for value in geometry['tool_axial_bounds_mm']]
        grip = robot.transform(self.device['TR01'], geometry['grip_mm'])
        dock_roll = approach['roll_deg']
        side = [row[1] for row in pose(grip, 0., dock_roll)[:3]]
        hover = cf.plus(grip, [0., 0., 1.], approach['clearance_height_mm'] - grip_adjustment)
        corner = cf.plus(hover, side, -approach['side_offset_mm'][identity])
        top = cf.plus(corner, [0., 0., 1.], approach['height_mm'])
        horizontal_end = cf.plus(hover, side, -approach['alignment_lead_mm'])
        entry = CornerPath(top, corner, horizontal_end, 0., 0., approach['corner_trim_mm'])
        axial = CornerPath(horizontal_end, hover, grip, 0., 0., approach['alignment_corner_mm'])
        side_scale = math.hypot(*entry.derivative(1., 1))
        axial_scale = math.hypot(*axial.derivative(0., 1))
        split = 2.5 + side_scale / (side_scale + axial_scale)
        aligned = self.leg(lambda u: pose(entry.pose(u)['position'], 0., dock_roll), 40, 2.5, split)
        final = self.leg(lambda u: pose(axial.pose(u)['position'], 0., dock_roll), 28, split, 3.5, aligned[-1][1])
        aligned.extend(final[1:])
        placement = [(2.5 * i / 40, vector_at(self.park, aligned[0][1], i / 40)) for i in range(41)]
        cassette = placement + aligned[1:]
        grasp_q = cassette[-1][1]
        high_dock = cf.plus(grip, [0., 0., 1.], approach['extraction_mm'])
        start = self.leg(lambda progress: pose(vector_at(grip, high_dock, progress), 0., dock_roll), 32, 0., 1., grasp_q)

        bottom, slot_axis = cf.pocket(self.station, self.cp, slot)
        index = pickup.placement([0., 0., 0.], -(slot - 1) * 360. / self.station['rotor']['slots'])
        rotor_frame = robot.multiply(self.device['CF01'], index)
        axis = transfer.direction(rotor_frame, slot_axis)
        standoff = self.cp['lift_travel'] + geometry['tool_axial_bounds_mm'][1]
        raised = robot.transform(rotor_frame, cf.plus(bottom, slot_axis, standoff))
        high_station = cf.plus(raised, axis, station_entry['axial_travel_mm'])
        yaw = math.degrees(math.atan2(self.device['CF01'][1][0], self.device['CF01'][0][0]))
        tilt = self.station['rotor']['tilt_from_vertical_deg']
        station_pose = lambda xyz: pose(xyz, tilt, station_entry['roll_deg'], yaw)
        last_q = self.inverse(station_pose(high_station))
        first_q = start[-1][1]
        loaded_offsets = self.route['loaded_joint_blend_offset_deg']
        transit = [(1. + 4. * (i / 48), joint_blend(first_q, last_q, loaded_offsets, i / 48))
                   for i in range(1, 49)]
        end = self.leg(lambda progress: station_pose(vector_at(high_station, raised, progress)),
                       36, 5., 6., last_q)
        carried = start + transit + end[1:]
        retreat = [(6. - time, q) for time, q in reversed(end)]
        retreat_offsets = station_entry['retreat_joint_blend_offset_deg']
        retreat.extend((1. + 4. * (i / 40), joint_blend(last_q, self.park, retreat_offsets, i / 40))
                       for i in range(1, 41))

        radius = geometry['radius_mm']
        tube = next(op['shape'] for op in self.cargo['operations'] if op['body'] == identity and op['action'] == 'create')
        sample_points = [[x, y, z] for x, y, z in itertools.product((-radius, radius), (-radius, radius),
                                                                  geometry['tool_axial_bounds_mm'])]
        return self.channels(sample, cassette, carried, retreat, sample_points, 2. * tube['radius'])

    def channels(self, sample, cassette, carried, retreat, sample_points, closed):
        arm = []
        audits = {}

        def move(label, nodes, material=()):
            points, audits[label] = self.fit(nodes, material)
            offset = arm[-1]['time_s'] if arm else 0.
            arm.extend({**entry, 'time_s': offset + entry['time_s']} for entry in points[int(bool(arm)):])
            return arm[-1]['time_s']

        def hold(duration):
            time = arm[-1]['time_s'] + duration
            arm.append(point(time, arm[-1][POSITION]))
            return time

        holds = self.route['jaw_holds_s']
        cassette_gap = self.cassette['gripper_overrides']['open_gap_mm']
        open_gap = self.gripper['open_gap_mm']
        dock = move('cassette_approach', cassette)
        grip = hold(holds['grasp'])
        above_support = move('carried', carried, sample_points)
        release = hold(holds['support_release'])
        back_home = move('withdraw_and_park', retreat)
        end = hold(holds['park_reset'])
        jaw = [point(t, [gap], JAW_FIELDS) for t, gap in (
            (0., cassette_gap), (dock, cassette_gap), (grip, closed),
            (above_support, closed), (release, open_gap), (back_home, open_gap), (end, cassette_gap))]
        return {**sample, 'points': arm, 'jaw_points': jaw, 'grip_s': grip, 'seat_s': release,
                'dynamics': audits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-preview', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    workspace = Workspace(args.stock_preview)
    samples = [workspace.track(sample) for sample in workspace.samples]
    program = {'format': FORMAT, 'source_files_sha256': workspace.pins,
               'stock_html_sha256': workspace.stock_sha256, 'home_joints_deg': workspace.park,
               'samples': samples, 'return_samples': [reversed_handoff(track) for track in reversed(samples)],
               'scope': 'Synthetic arm and jaw PVA with modeled dynamics. Independent native clearance required.'}
    args.out.write_text(json.dumps(program, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
