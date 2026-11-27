"""Compile a synthetic CF01 delivery trace for the Lab 3.003 walkthrough."""

import json
import math
from pathlib import Path

import assembly_model as assembly
import centrifuge_model as cf
import centrifuge_protocol as protocol
import cf01_empty_seat_handoff as support
import cf01_rack_batch as batch
import lab_layout_model as layout
import robot_spec as robot
from centrifuge_control import Simulator


ROOT = cf.ROOT
SOURCE = ROOT / 'model/lab3003-cf01-cycle.shared.json'


def _load_source():
    definition = json.loads(SOURCE.read_text())
    if (not isinstance(definition, dict) or set(definition) != {'format', 'laboratory_id', 'sources', 'samples'}
            or definition['format'] != 'solidcraftbot.lab3003-cf01-cycle/1'):
        raise ValueError('Unsupported Lab 3.003 CF01 cycle source')
    refs = definition['sources']
    if (not isinstance(refs, dict) or set(refs) != {'laboratories', 'simulation_fixture', 'motion_limits'}
            or any(not isinstance(ref, dict) or set(ref) != {'source', 'source_sha256'}
                   for ref in refs.values())):
        raise ValueError('Pinned laboratory, simulation fixture and limits sources are required')
    samples = definition['samples']
    if (not isinstance(samples, list) or len(samples) != 2
            or any(not isinstance(sample, dict) or set(sample) != {'id', 'slot'}
                   or not isinstance(sample['id'], str) or not sample['id']
                   or type(sample['slot']) is not int for sample in samples)
            or samples[0]['id'] == samples[1]['id']):
        raise ValueError('Two distinct cassette tube identities and CF01 slots are required')
    return definition, {name: assembly.validate_reference(ref) for name, ref in refs.items()}


def _bound_sources(laboratory_id, laboratories_path, samples):
    laboratories = json.loads(laboratories_path.read_text())['laboratories']
    lab, = (lab for lab in laboratories if lab['id'] == laboratory_id)
    if (lab['transporter_dock']['instance'] != 'TR01'
            or lab['bench_layout']['devices'].get('ArmC') != 'Arm'
            or lab['bench_layout']['devices'].get('CF01') != 'CF01'):
        raise ValueError('The Lab 3.003 TR01 dock and ArmC/CF01 bench binding are required')
    layout_source = assembly.validate_reference(lab['layout_source'])
    if layout_source != layout.SOURCE:
        raise ValueError('The existing L01 equipment layout is required')
    source = layout.load(validate_builds=False)
    instances = {item['id']: item for item in source['instances']}
    vehicle = instances['TR01']
    provider = layout.provider(vehicle['asset'])
    construction = layout.instance_source(source, vehicle)
    expanded = provider.expanded(construction, provider.parameters(construction),
                                 layout.instance_variant(construction, vehicle))
    bodies = {item['id']: item['role'] for item in expanded['bodies']}
    if (bodies.get('TransportCover') != 'removable_cover_envelope'
            or any(bodies.get(sample['id']) != 'closed_tube_reference_envelope' for sample in samples)):
        raise ValueError('The modeled cover and both cassette tubes are required')
    station_instance = instances['CF01']
    station = layout.instance_source(source, station_instance)
    slots = station['rotor']['slots']
    if any(not 1 <= sample['slot'] <= slots for sample in samples) or (
            abs(samples[1]['slot'] - samples[0]['slot']) != slots // 2):
        raise ValueError('Two opposite CF01 slots are required')
    return station, [layout_source,
                     assembly.validate_reference(source['assets'][vehicle['asset']]),
                     assembly.validate_reference(source['assets'][station_instance['asset']])]


def _quintic_duration(distance, velocity, acceleration, jerk):
    # Extrema of the unit rest-to-rest quintic: 15/8, 10/sqrt(3), 60.
    distance = abs(distance)
    return max(15 * distance / (8 * velocity),
               math.sqrt(10 * distance / (math.sqrt(3) * acceleration)),
               (60 * distance / jerk) ** (1 / 3))


def _arm_path_timings(paths, samples, *, returning=False):
    if not isinstance(paths, list) or len(paths) != len(samples):
        raise ValueError('One ordered arm path for each supported transfer is required')
    for path, sample in zip(paths, samples):
        if (not isinstance(path, dict) or not {'id', 'slot', 'points', 'jaw_points', 'grip_s', 'seat_s'} <= path.keys()
                or path['id'] != sample['id'] or type(path['slot']) is not int or path['slot'] != sample['slot']
                or path.get('direction', 'load') != ('unload' if returning else 'load')):
            raise ValueError('Arm path must match the ordered tube and selected pocket')
        for key in ('points', 'jaw_points'):
            track = path[key]
            if not isinstance(track, list) or len(track) < 2:
                raise ValueError('Arm and jaw tracks need time-stamped start and end points')
            times = [point.get('time_s') if isinstance(point, dict) else None for point in track]
            if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times)
                    or times[0] != 0 or any(a >= b for a, b in zip(times, times[1:]))):
                raise ValueError('Arm and jaw tracks must use a finite strictly increasing local clock')
        end = path['points'][-1]['time_s']
        grip, release = path['grip_s'], path['seat_s']
        if (any(type(t) not in (int, float) or not math.isfinite(t) for t in (grip, release))
                or not 0 < grip < release < end or not release <= path['jaw_points'][-1]['time_s'] <= end):
            raise ValueError('Grasp, release and return to park must be ordered')
        if returning and path['jaw_points'][-1]['time_s'] != end:
            raise ValueError('Return arm and jaw tracks must end together')
    return paths


def compile_cycle(*, cover_removed=True, feedback=None, arm_paths=None, return_paths=None):
    """Compile fictional confirmation snapshots after TR01 has stopped at the dock.

    Optional feedback(event, sample) supplies simulated observations. Sample is
    None for cover removal and otherwise has id and slot. A rejected observation
    aborts compilation. Mechanism transitions are visual keyframes, with logical
    simulator decisions at their endpoints. Transfer holds encode observation
    ordering only and contain no validated arm or carried-vessel movement.
    Providing arm paths selects the separate raised-support handoff. This
    compiler checks timing and ownership; the geometry proof is independent.
    Optional return paths unload the spun tubes to their original cassette
    slots in reverse order and gate the departure on cover replacement.
    """
    if cover_removed is not True:
        raise ValueError('TR01 transport cover removal must be confirmed')
    definition, sources = _load_source()
    samples = definition['samples']
    paths = _arm_path_timings(arm_paths, samples) if arm_paths is not None else None
    return_samples = list(reversed(samples))
    if return_paths is not None:
        if paths is None:
            raise ValueError('Return paths require the supported loading paths')
        return_paths = _arm_path_timings(return_paths, return_samples, returning=True)
    station, source_paths = _bound_sources(definition['laboratory_id'], sources['laboratories'], samples)
    fixture = batch.load(sources['simulation_fixture'])
    station_motion = json.loads(sources['motion_limits'].read_text())['limits']
    poll = fixture['command_execution']['poll_interval_s']
    pin_keyframes = protocol.load()['animation']['keyframes']
    pin_open_s = pin_keyframes[1]['time_s'] - pin_keyframes[0]['time_s']
    pin_close_s = pin_keyframes[-1]['time_s'] - pin_keyframes[-2]['time_s']
    slots = station['rotor']['slots']
    fictitious_masses = {sample['rotor_slot']: sample['mass_g'] for sample in fixture['samples']}
    transported = {sample['id'] for sample in samples}
    rotor = {}
    gripper = None
    now = 0.0
    simulator = Simulator if paths is None else support.EmptySeatHandoffSimulator
    sim = simulator(spec=station, clock=lambda: now, qualification=fixture['simulation_qualification'],
                    initial_slots={slot: {'present': False, 'seated': False, 'mass_g': None}
                                   for slot in range(1, slots + 1)})
    token = sim.execute('acquire', client_id='lab3003-cf01-cycle')['token']
    bridge = protocol.MockProtocol(sim)
    steps = []
    timed_samples = []
    timed_returns = []
    pusher_mm = 0
    lift_mm = 0
    pusher_sample = None
    returned = []
    display_rotor = None
    refresh = station['handling']['owner_timeout_s'] / 2
    next_heartbeat = refresh

    def advance(seconds):
        nonlocal now, next_heartbeat
        target = now + seconds
        while next_heartbeat <= target:
            now = next_heartbeat
            sim.execute('heartbeat', token)
            next_heartbeat += refresh
        now = target

    def snapshot(phase, sample=None, **display):
        state = sim.execute('status')
        if state['fault']:
            raise ValueError('CF01 reported a synthetic fault: ' + state['fault'])
        support_state = {} if paths is None else {
            'pusher_mm': pusher_mm, 'lift_mm': lift_mm, 'pusher_sample_id': pusher_sample}
        return_state = {} if return_paths is None else {
            'returned': returned[:], 'transport_ready': phase == 'transport_ready'}
        steps.append({'time_s': now, 'phase': phase, 'tube_id': sample['id'] if sample else None,
                      'lid_deg': state['mechanisms']['lid_angle_deg'],
                      'latch_mm': state['mechanisms']['locking_pin_retraction_mm'],
                      'rotor_deg': state['encoder_deg'] if display_rotor is None else display_rotor,
                      'rpm': state['speed_rpm'],
                      'seated': list(rotor.values()), 'arm_clear': state['robot_clear'],
                      'lid_locked': state['lid_locked'], 'brake_held': state['brake_held'],
                      'cover_removed': cover_observed, **support_state, **return_state, **display})

    def observe(event, sample, required, *, cassette=False):
        if feedback is not None:
            reply = feedback(event, None if sample is None else dict(sample))
        elif sample is None:
            reply = {'cover_removed': cover_removed, 'cover_replaced': True}
        else:
            reply = {**batch.synthetic_feedback(event, sample), 'rotor_slot': sample['slot']}
            if paths is not None:
                reply.update(empty_confirmed=True, extended_confirmed=True, rested_confirmed=True,
                             parked_confirmed=True)
            if return_paths is not None:
                reply.update(presented_confirmed=True, cassette_slot=sample['id'],
                             destination_empty=True, cassette_seated=True)
        if (not isinstance(reply, dict) or any(reply.get(flag) is not True for flag in required)
                or sample is not None and (reply.get('sample_id') != sample['id']
                                           or type(reply.get('rotor_slot')) is not int
                                           or reply['rotor_slot'] != sample['slot'])
                or cassette and reply.get('cassette_slot') != sample['id']):
            raise ValueError('Missing, negative or mismatched synthetic confirmation: ' + event)

    def lift_time(distance):
        linear = station_motion['station_linear']
        return _quintic_duration(distance, linear['velocity_mm_s'], linear['acceleration_mm_s2'],
                                 linear['jerk_mm_s3'])

    def grasp(sample):
        nonlocal gripper
        if gripper is not None or sample['id'] not in transported or sample['slot'] in rotor:
            raise ValueError('Synthetic transfer source, gripper or destination disagrees')
        observe('grasp', sample, ('grasp_confirmed', 'source_empty'))
        transported.remove(sample['id'])
        gripper = sample['id']
        sim.robot_clear = False
        snapshot('arm_transfer', sample)

    def supported_transfer(sample, path, mass):
        nonlocal gripper, pusher_mm, lift_mm, pusher_sample
        identity = {'sample_id': sample['id'], 'slot': sample['slot']}

        observe('empty_slot', sample, ('empty_confirmed',))
        sim.execute('begin_raise_empty_support', token, **identity, empty_confirmed=True)
        snapshot('pusher_raising', sample)
        gap = sim.p['park_gap']
        travel = sim.p['lift_travel']
        advance(lift_time(gap + travel))
        observe('support_extended', sample, ('extended_confirmed',))
        sim.execute('confirm_empty_support_extended', token, **identity, extended_confirmed=True)
        pusher_mm = gap + travel
        arm_started = now
        sim.robot_clear = False
        snapshot('pusher_raised', sample)

        advance(path['grip_s'])
        grasp(sample)
        gripped = now
        advance(path['seat_s'] - path['grip_s'])
        observe('support_release', sample, ('rested_confirmed', 'cap_closed_confirmed', 'released_confirmed'))
        if gripper != sample['id']:
            raise ValueError('Gripper ownership must match the supported tube')
        sim.execute('confirm_tube_on_support', token, **identity, rested_confirmed=True,
                    cap_closed_confirmed=True, released_confirmed=True, mass_g=mass)
        pusher_sample, gripper, lift_mm = gripper, None, travel
        supported = now
        snapshot('pusher_transfer', sample)

        advance(path['points'][-1]['time_s'] - path['seat_s'])
        observe('arm_clear', sample, ('workspace_clear',))
        sim.robot_clear = True
        cleared = now
        snapshot('arm_clear', sample)
        advance(poll)
        sim.execute('begin_lower_supported_tube', token, **identity, workspace_clear_confirmed=True)
        snapshot('lowering', sample)
        advance(lift_time(travel))
        observe('seat', sample, ('seated_confirmed', 'cap_closed_confirmed'))
        sim.execute('confirm_supported_tube_seated', token, **identity, seated_confirmed=True)
        pusher_mm, lift_mm = gap, 0
        snapshot('pocket_reached', sample)
        advance(lift_time(gap))
        observe('support_parked', sample, ('parked_confirmed',))
        state = sim.execute('confirm_empty_support_parked', token, **identity, parked_confirmed=True)
        if (pusher_sample != sample['id'] or state['pusher_handoff'] is not None
                or state['slots'][sample['slot']] != {'present': True, 'seated': True, 'mass_g': mass}):
            raise ValueError('Supported tube ownership must match the parked, seated station state')
        rotor[sample['slot']] = pusher_sample
        pusher_mm, pusher_sample = 0, None
        snapshot('seated', sample)
        timed_samples.append({**path, 'arm_start_s': arm_started, 'grip_s': gripped,
                              'support_release_s': supported, 'arm_clear_s': cleared, 'pusher_lowered_s': now})

    def return_to_cassette(sample, path):
        nonlocal gripper, pusher_mm, lift_mm, pusher_sample
        identity, slot = sample['id'], sample['slot']
        gap, travel = sim.p['park_gap'], sim.p['lift_travel']
        if (rotor.get(slot) != identity or identity in transported
                or gripper is not None or pusher_sample is not None):
            raise ValueError('Return requires the correct seated tube, empty gripper and free cassette slot')
        observe('cassette_empty', sample, ('destination_empty',), cassette=True)
        advance(poll)
        snapshot('pickup_presenting', sample)
        advance(lift_time(gap))
        state = sim.execute('present_tube', token)
        if (state['indexed_slot'] != slot or not state['grip_frame']['valid']
                or state['lift_mm'] != travel or state['slots'][slot]['seated']):
            raise ValueError('Return requires the indexed tube presented on the raised support')
        # At contact the tube begins to follow the physical support. The
        # simulator command acknowledges the target; lift_mm animates travel.
        pusher_sample = rotor.pop(slot)
        pusher_mm = gap
        snapshot('pickup_contact', sample)
        advance(lift_time(travel))
        observe('pickup_presented', sample, ('presented_confirmed',))
        pusher_mm, lift_mm = gap + travel, travel
        arm_started = now
        sim.robot_clear = False
        snapshot('pickup_raised', sample)

        advance(path['grip_s'])
        observe('pickup_grasp', sample, ('grasp_confirmed', 'source_empty'))
        state = sim.execute('confirm_removed', token, grasp_confirmed=True, tube_absent=True)
        if (pusher_sample != identity or state['slots'][slot]['present'] or state['lift_mm'] != travel):
            raise ValueError('Return grip and indexed pocket observations disagree')
        gripper, pusher_sample, lift_mm = pusher_sample, None, 0
        gripped = now
        snapshot('pickup_grasp', sample)

        advance(path['seat_s'] - path['grip_s'])
        observe('cassette_seat', sample, ('cassette_seated', 'released_confirmed', 'cap_closed_confirmed'),
                cassette=True)
        if gripper != identity or identity in transported:
            raise ValueError('Only the tube held by the gripper can be returned to its empty cassette slot')
        transported.add(gripper)
        returned.append(gripper)
        gripper = None
        released = now
        snapshot('cassette_seated', sample)

        advance(path['points'][-1]['time_s'] - path['seat_s'])
        observe('return_arm_clear', sample, ('workspace_clear',))
        sim.robot_clear = True
        cleared = now
        snapshot('return_arm_clear', sample)
        advance(poll)
        snapshot('pickup_pusher_retracting', sample)
        advance(lift_time(gap + travel))
        observe('pickup_pusher_parked', sample, ('parked_confirmed',))
        state = sim.execute('retract_lift', token)
        if state['lift_mm'] != 0 or state['slots'][slot]['present']:
            raise ValueError('Return requires the selected pocket empty and the pusher parked')
        pusher_mm = 0
        snapshot('pickup_pusher_parked', sample)
        timed_returns.append({**path, 'arm_start_s': arm_started, 'grip_s': gripped,
                              'cassette_release_s': released, 'arm_clear_s': cleared, 'pusher_parked_s': now})

    cover_observed = False
    snapshot('docked')
    advance(poll)
    observe('cover_removed', None, ('cover_removed',))
    cover_observed = True
    snapshot('cover_removed')

    closed_deg = cf.pose(station, sim.p, 'closed')['Lid']
    open_deg = cf.pose(station, sim.p, 'open')['Lid']
    lid_limits = station_motion['station_lid']
    lid_s = _quintic_duration(open_deg - closed_deg, min(lid_limits['velocity_deg_s'],
        station['mechanisms']['lid']['nominal_lid_speed_deg_s']),
        lid_limits['acceleration_deg_s2'], lid_limits['jerk_deg_s3'])
    pins = [sim.p['latch_travel']] * 2
    index_limits = station_motion['station_rotor']
    index_deg_s = 6 * min(index_limits['velocity_rpm'], station['handling']['index_limit_rpm'])

    def open_slot(sample, *, returning=False):
        nonlocal display_rotor
        prefix = 'return_' if returning else ''
        slot = sample['slot']
        target = -360 * (slot - 1) / slots
        current = display_rotor if returning else sim.encoder_deg
        rotation = math.remainder(target - current, 360) if returning else target - current
        move_s = _quintic_duration(rotation, index_deg_s,
                                   index_limits['acceleration_deg_s2'], index_limits['jerk_deg_s3'])
        advance(poll)
        snapshot(prefix + 'indexing', sample, brake_held=not move_s)
        advance(max(move_s, poll))
        state = sim.execute('index', token, slot=slot)
        if not (state['index_confirmed'] and state['indexed_slot'] == slot and state['brake_held']):
            raise ValueError('CF01 index and holding brake must be confirmed')
        if returning:
            display_rotor = current + rotation
        snapshot(prefix + 'indexed', sample)
        advance(poll)
        snapshot(prefix + 'unlocking', sample)
        advance(pin_open_s)
        snapshot(prefix + 'opening', sample, latch_mm=pins[:], lid_locked=False)
        advance(lid_s)
        sim.execute('open_lid', token)
        snapshot(prefix + 'open', sample)

    def close_station(sample, *, returning=False):
        prefix = 'return_' if returning else ''
        advance(poll)
        snapshot(prefix + 'closing', sample)
        advance(lid_s)
        snapshot(prefix + 'locking', sample, lid_deg=closed_deg)
        advance(pin_close_s)
        sim.execute('close_lid', token)
        snapshot(prefix + 'locked', sample)

    for index, sample in enumerate(samples):
        open_slot(sample)
        slot = sample['slot']
        advance(poll)
        mass = fictitious_masses[slot]
        if paths is not None:
            supported_transfer(sample, paths[index], mass)
        else:
            grasp(sample)
            advance(poll)
            observe('seat', sample, ('seated_confirmed', 'cap_closed_confirmed', 'released_confirmed'))
            state = sim.execute('confirm_seated', token, mass_g=mass, seated_confirmed=True,
                                cap_closed_confirmed=True)
            if (gripper != sample['id'] or state['indexed_slot'] != slot
                    or state['slots'][slot] != {'present': True, 'seated': True, 'mass_g': mass}):
                raise ValueError('Synthetic seating or sample identity disagrees with CF01')
            rotor[slot] = gripper
            gripper = None
            snapshot('seated', sample)
            advance(poll)
            observe('arm_clear', sample, ('workspace_clear',))
            sim.robot_clear = True
            snapshot('arm_clear', sample)

        close_station(sample)

    if (transported or gripper is not None or pusher_sample is not None
            or rotor != {sample['slot']: sample['id'] for sample in samples}):
        raise ValueError('Both distinct tubes must be confirmed seated before spin')
    advance(poll)
    spin = bridge.begin('start', token, **fixture['spin'])
    if spin['phase'] != 'running':
        raise ValueError('CF01 did not begin the balanced synthetic run')
    spin_started = now
    snapshot('spinning')
    spin_rpm = steps[-1]['rpm']
    advance(fixture['spin']['duration_s'])
    if bridge.poll(spin['id'])['phase'] != 'braking':
        raise ValueError('CF01 synthetic service braking must be observed')
    brake_started = now
    brake_angle = steps[-1]['rotor_deg'] + 6 * spin_rpm * (brake_started - spin_started)
    snapshot('braking', rotor_deg=brake_angle)
    advance(station['mechanisms']['braking']['simulation_stop_s'])
    # Ensure the simulator observes the exact braking boundary despite rounding.
    now = math.nextafter(now, math.inf)
    done = bridge.poll(spin['id'])
    if done['phase'] != 'succeeded' or not all(done['state'][key] for key in
            ('standstill_confirmed', 'parking_brake_held', 'lid_locked')):
        raise ValueError('CF01 run must finish at confirmed standstill with its lid locked')
    stop_angle = brake_angle + 3 * spin_rpm * (now - brake_started)
    stopped_at = now
    snapshot('stopped', rotor_deg=stop_angle)
    return_trace = {}
    if return_paths is not None:
        display_rotor = stop_angle
        for sample, path in zip(return_samples, return_paths):
            open_slot(sample, returning=True)
            return_to_cassette(sample, path)
            close_station(sample, returning=True)
        state = sim.execute('status')
        if (rotor or gripper is not None or pusher_sample is not None or pusher_mm != 0
                or transported != {sample['id'] for sample in samples}
                or any(item['present'] for item in state['slots'].values())
                or not all(state[key] for key in ('brake_held', 'standstill_confirmed', 'robot_clear', 'lid_locked'))):
            raise ValueError('Departure requires the returned load, clear arm, parked pusher and locked empty rotor')
        advance(poll)
        observe('cover_replaced', None, ('cover_replaced',))
        cover_observed = False
        snapshot('transport_ready')
        return_trace = {'return_samples': timed_returns, 'transport_ready_s': now}
    sim.execute('release', token)

    source_paths += [SOURCE, *sources.values(), Path(__file__), protocol.SOURCE,
                     ROOT / 'scripts/centrifuge_control.py', ROOT / 'scripts/cf01_rack_batch.py',
                     ROOT / 'scripts/centrifuge_protocol.py', ROOT / 'scripts/centrifuge_model.py']
    if paths is not None:
        source_paths += [support.SOURCE, Path(support.__file__)]
    return {'steps': steps, 'samples': samples if paths is None else timed_samples, 'duration_s': now,
            'spin_started_s': spin_started, 'brake_started_s': brake_started, 'stopped_s': stopped_at,
            'synthetic': True, 'hardware_qualified': False, 'arm_motion_checked': False,
            'scope': ('Synthetic supported handoff with station timing and explicit observations. Arm geometry '
                      'and physical operation are separate evidence.' if paths is not None else
                      'Abstract synthetic confirmation and station playback. No arm path, cover handling path or physical operation is certified.'),
            'source_files_sha256': {str(path.relative_to(ROOT)): robot.digest(path) for path in source_paths},
            **return_trace}
