"""Source-framed static pneumatic routing and finite demonstrated length bands.

Robot kinematics and exact line/arc operations are shared with the other model
compilers. This module does not import a CAD, select hardware or qualify motion.
"""
import json
import math

from robot_spec import evaluate
import pneumatic_hose as hose
import robot_spec as robot
import spatial_hose_carrier as carrier


class RoutingEvidenceError(ValueError):
    """Malformed evaluator evidence must not be classified as geometric failure."""


class RouteClearanceError(ValueError):
    def __init__(self, message, witness):
        super().__init__(message)
        self.witness = witness


def _number(value, label, nonnegative=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (nonnegative and value < 0)):
        raise ValueError('Invalid finite routing quantity: '+label)
    return float(value)


def _vector(values, parameters):
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError('Routing frame needs three coordinates')
    return [_number(evaluate(v, parameters), 'frame coordinate') for v in values]


def _direction(matrix, vector):
    return [sum(matrix[i][j]*vector[j] for j in range(3)) for i in range(3)]


def _line(start, end):
    length = math.dist(start, end)
    if length < 1e-9:
        return None
    return {'kind': 'line', 'start_mm': list(start), 'end_mm': list(end), 'length_mm': length}


def _frame(record, values, frames):
    if set(record) != {'link', 'origin', 'tangent', 'x', 'clamp_length_mm'}:
        raise ValueError('Routing frames require link, origin, tangent, x and clamp length')
    matrix = frames[record['link']]
    tangent = hose._unit(_direction(matrix, _vector(record['tangent'], values)))
    x = hose._unit(_direction(matrix, _vector(record['x'], values)))
    if abs(hose._dot(tangent, x)) > 1e-8:
        raise ValueError('Routing frame tangent and x axis must be perpendicular')
    center = robot.transform(matrix, _vector(record['origin'], values))
    length = _number(evaluate(record['clamp_length_mm'], values), 'clamp length', True)
    return {'center_mm': center, 'tangent': tangent, 'x_axis': x,
            'y_axis': hose._cross(tangent, x), 'link': record['link'],
            'clamp_length_mm': length,
            'start_mm': hose._sub(center, hose._mul(tangent, length/2)),
            'end_mm': hose._add(center, hose._mul(tangent, length/2))}


def _socket_frame(interface, entering):
    start = interface['bend_start_mm'] if entering else interface['material_end_mm']
    end = interface['material_end_mm'] if entering else interface['bend_start_mm']
    tangent = hose._mul(interface['outward'], -1 if entering else 1)
    return {'center_mm': hose._mul(hose._add(start, end), .5),
            'tangent': tangent, 'x_axis': interface['x_axis'],
            'y_axis': hose._cross(tangent, interface['x_axis']),
            'link': interface['component'], 'clamp_length_mm': math.dist(start, end),
            'start_mm': list(start), 'end_mm': list(end)}


def bare_span(start, end, start_tangent, end_tangent, minimum_radius, *,
              tangent_distance_multipliers=None, sample_step_mm=3.0, candidate_check=None):
    """Choose a shortest geometric candidate in an explicitly bounded family.

    The equal-tangent biarc remains a candidate. Declared tangent distances add
    exact fixed-radius fillet candidates, avoiding an unnecessarily long major
    biarc. Self-clearance and external clearance belong to the complete route.
    """
    if tangent_distance_multipliers is None:
        path = carrier.biarc_path(start, end, start_tangent, end_tangent, minimum_radius,
                                  sample_step_mm=sample_step_mm)
        if candidate_check is not None:
            check = candidate_check(path)
            if not isinstance(check, dict) or type(check.get('passed')) is not bool or not check.get('scope'):
                raise RoutingEvidenceError('Bare-span clearance evidence needs a boolean result and scope')
            try:
                json.dumps(check, allow_nan=False)
            except (ValueError, TypeError) as error:
                raise RoutingEvidenceError('Bare-span clearance evidence must be finite and serializable') from error
            if not check['passed']:
                raise RouteClearanceError('The endpoint biarc has no demonstrated source clearance',
                    {'kind': 'bare_span_clearance', 'clearance_rejections': [check]})
            path['bare_fit'] = {'family': 'endpoint_biarc', 'candidate_count': 1, 'selected_clearance': check}
        return path
    if not isinstance(tangent_distance_multipliers, (list, tuple)) or not tangent_distance_multipliers:
        raise ValueError('Bare-span fitting needs declared positive tangent-distance multipliers')
    multipliers = [_number(value, 'tangent-distance multiplier') for value in tangent_distance_multipliers]
    if min(multipliers) <= 0:
        raise ValueError('Tangent-distance multipliers must be positive')
    start, end = hose._point(start), hose._point(end)
    t0, t1 = hose._unit(hose._point(start_tangent)), hose._unit(hose._point(end_tangent))
    candidates, failures = [], []
    try:
        path = carrier.biarc_path(start, end, t0, t1, minimum_radius, sample_step_mm=sample_step_mm)
        candidates.append((path, {'family': 'endpoint_biarc'}))
    except ValueError as error:
        failures.append({'family': 'endpoint_biarc', 'error': str(error), 'witness': getattr(error, 'witness', None)})
    for first in multipliers:
        for second in multipliers:
            d0, d1 = first*minimum_radius, second*minimum_radius
            try:
                path = hose.centerline([start, hose._add(start, hose._mul(t0, d0)),
                    hose._sub(end, hose._mul(t1, d1)), end], minimum_radius, sample_step_mm)
                hose._joined_path(path)
                candidates.append((path, {'family': 'fixed_radius_tangent_fillets',
                                          'tangent_distances_mm': [d0, d1]}))
            except ValueError as error:
                failures.append({'family': 'fixed_radius_tangent_fillets', 'tangent_distances_mm': [d0, d1],
                                 'error': str(error), 'witness': getattr(error, 'witness', None)})
    if not candidates:
        raise hose.HoseBendError('No declared bare-span candidate meets endpoint tangents and hard radius',
            {'kind': 'bare_span_family', 'start_mm': start, 'end_mm': end,
             'required_radius_mm': minimum_radius, 'candidate_count': 1+len(multipliers)**2,
             'rejected_candidates': failures})
    rejected = []
    ordered = sorted(candidates, key=lambda row: row[0]['length_mm'])
    selected_check = None
    for index, (path, choice) in enumerate(ordered):
        if candidate_check is None:
            break
        selected_check = candidate_check(path)
        if (not isinstance(selected_check, dict) or type(selected_check.get('passed')) is not bool
                or not selected_check.get('scope')):
            raise RoutingEvidenceError('Bare-span clearance evidence needs a boolean result and scope')
        try:
            json.dumps(selected_check, allow_nan=False)
        except (ValueError, TypeError) as error:
            raise RoutingEvidenceError('Bare-span clearance evidence must be finite and serializable') from error
        if selected_check['passed']:
            break
        rejected.append({**choice, 'length_mm': path['length_mm'], 'clearance': selected_check})
    else:
        raise RouteClearanceError('No declared bare-span geometric candidate has demonstrated source clearance',
            {'kind': 'bare_span_clearance', 'start_mm': start, 'end_mm': end,
             'candidate_count': 1+len(multipliers)**2, 'clearance_rejections': rejected,
             'geometric_rejections': failures})
    path['bare_fit'] = {**choice, 'candidate_count': 1+len(multipliers)**2,
                        'geometrically_feasible_candidate_count': len(candidates),
                        'geometric_rejections': failures, 'clearance_rejections': rejected,
                        'selected_clearance': selected_check,
                        'longer_geometric_candidates_not_checked': len(ordered)-index-1,
                        'scope': 'Shortest of declared geometric candidates; full-route self/external clearance checked separately'}
    return path


def route(spec, p, frames, mounted, slack, context):
    """Compile exact spans between physical frames, with no shortened radii.

    ``context['routing_config']`` supplies frames, sequence, guide and optional
    joint-to-frame crossing names. ``connection_interfaces`` is the root's
    world-interface callback (or a mapping already evaluated for this pose).
    An ordinary frame contributes its centered straight clamp exactly once.
    The guide's endpoint straights belong to its nominal N*pitch length.
    """
    config = context['routing_config']
    values = {**context['parameters'], **p, 'serviceLoop': _number(slack, 'service loop', True)}
    interfaces = context['connection_interfaces']
    if callable(interfaces):
        interfaces = interfaces(spec, p, mounted)
    evaluated = {name: _frame(record, values, frames) for name, record in config['frames'].items()}
    if 'pump' in evaluated or 'tip' in evaluated:
        raise ValueError('Pump and tip frames come from the connection interfaces')
    evaluated['pump'] = _socket_frame(interfaces['pump'], False)
    evaluated['tip'] = _socket_frame(interfaces['tip'], True)
    sequence = config['sequence']
    if (not isinstance(sequence, list) or len(sequence) < 4 or sequence[0] != 'pump'
            or sequence[-1] != 'tip' or len(set(sequence)) != len(sequence)
            or set(sequence) != set(evaluated)):
        raise ValueError('Routing sequence must visit every frame exactly once from pump to tip')
    guide = config['guide'];guide_pair = (guide['from'], guide['to'])
    if guide_pair not in list(zip(sequence, sequence[1:])):
        raise ValueError('The guide must connect consecutive routing frames')
    if any(evaluated[name]['clamp_length_mm'] != 0 for name in guide_pair):
        raise ValueError('Guide anchor straights belong inside its nominal path, not duplicate node clamps')
    external = hose._endpoint_straights([evaluate(value, values) for value in guide.get('external_straights_mm', [0, 0])])
    internal = hose._endpoint_straights([evaluate(value, values) for value in guide['endpoint_straights_mm']])
    entry, exit = [evaluated[name] for name in guide_pair]
    entry['start_mm'] = hose._sub(entry['center_mm'], hose._mul(entry['tangent'], external[0]))
    exit['end_mm'] = hose._add(exit['center_mm'], hose._mul(exit['tangent'], external[1]))
    minimum = p['hoseBendRadius'];step = _number(config.get('sample_step_mm', 3.0), 'route sample step')
    if step <= 0:
        raise ValueError('Route sample step must be positive')
    segments, parts, guide_path = [], [], None
    for index, name in enumerate(sequence):
        frame = evaluated[name]
        fixed = _line(frame['start_mm'], frame['end_mm'])
        if fixed:
            if name in ('pump', 'tip'):
                interface = interfaces[name]
                stations = [interface[key] for key in ('material_end_mm', 'socket_mouth_mm',
                                                       'unsupported_exit_mm', 'bend_start_mm')]
                kinds = ['inserted', 'socket_strain_relief', 'connector_straight_lead']
                if name == 'tip':
                    stations.reverse();kinds.reverse()
                for kind, start, end in zip(kinds, stations, stations[1:]):
                    piece = _line(start, end)
                    if piece is None:
                        raise ValueError('Socket material regions must have positive length')
                    parts.append({'id': name+'_'+kind, 'kind': kind, 'length_mm': piece['length_mm'],
                                  'segment_start_index': len(segments), 'segment_count': 1})
                    segments.append(piece)
            else:
                parts.append({'id': name+'_external_guide_lead' if name in guide_pair else name,
                              'kind': 'bare_span' if name in guide_pair else 'clip_straight', 'length_mm': fixed['length_mm'],
                              'segment_start_index': len(segments), 'segment_count': 1})
                segments.append(fixed)
        if index == len(sequence)-1:
            continue
        after = sequence[index+1];next_frame = evaluated[after]
        if (name, after) == guide_pair:
            search = evaluated[guide['search_frame']]
            axes = [search['x_axis'], search['y_axis'], search['tangent']]
            profile = context['carrier_profile']
            key = json.dumps([profile, frame['end_mm'], next_frame['start_mm'], frame['tangent'],
                              next_frame['tangent'], axes, internal], sort_keys=True)
            cache = context.setdefault('framed_carrier_paths', {})
            if key not in cache:
                cache[key] = carrier.fit(profile, frame['end_mm'], next_frame['start_mm'],
                    frame['tangent'], next_frame['tangent'], search_axes=axes,
                    endpoint_straights_mm=internal)
            span = cache[key];guide_path = span
            kind = 'nominal_carrier'
        else:
            try:
                multipliers = config.get('bare_fit', {}).get('tangent_distance_multipliers')
                checker = context.get('bare_span_clearance')
                key = json.dumps([frame['end_mm'], next_frame['start_mm'], frame['tangent'],
                                  next_frame['tangent'], minimum, step, multipliers,
                                  frames if checker else None, mounted if checker else None])
                cache = context.setdefault('framed_bare_paths', {})
                if key not in cache:
                    cache[key] = bare_span(frame['end_mm'], next_frame['start_mm'],
                        frame['tangent'], next_frame['tangent'], minimum,
                        tangent_distance_multipliers=multipliers, sample_step_mm=step,
                        candidate_check=(lambda candidate: checker(candidate, name, after, frames, mounted)) if checker else None)
                span = cache[key]
            except hose.HoseBendError as error:
                raise hose.HoseBendError('Routing span '+name+' -> '+after+': '+str(error),
                                         {**error.witness, 'from_frame': name, 'to_frame': after}) from error
            except RouteClearanceError as error:
                raise RouteClearanceError('Routing span '+name+' -> '+after+': '+str(error),
                    {**error.witness, 'from_frame': name, 'to_frame': after}) from error
            kind = 'bare_span'
        record = {'id': name+'__'+after, 'kind': kind, 'length_mm': span['length_mm'],
                  'segment_start_index': len(segments), 'segment_count': len(span['segments'])}
        if 'bare_fit' in span:
            record['bare_fit'] = span['bare_fit']
        parts.append(record)
        segments.extend(span['segments'])
    if guide_path is None:
        raise ValueError('No carrier span was compiled')
    controls = [evaluated[name]['center_mm'] for name in sequence]
    path = carrier._path(segments, controls, minimum, step)
    hose._joined_path(path)
    path['carrier_path'] = guide_path
    path['routing_frames'] = evaluated
    crossings = {}
    joints = {joint['id']: joint for joint in context['arm']['joints']}
    crossing_indices = {}
    for joint_id, reference in config.get('crossings', {}).items():
        if isinstance(reference, dict):
            if set(reference) != {'interface', 'station'} or reference['interface'] not in interfaces:
                raise ValueError('Crossing interfaces need explicit interface and station names')
            station = reference['station']
            if station not in ('material_end_mm', 'pneumatic_junction_mm', 'socket_mouth_mm',
                               'unsupported_exit_mm', 'bend_start_mm'):
                raise ValueError('Unsupported crossing interface station')
            point = interfaces[reference['interface']][station]
            frame_id = reference['interface']+'.'+station
            crossing_indices[joint_id] = len(controls)
            controls.append(list(point))
        else:
            frame_id = reference;point = evaluated[frame_id]['center_mm']
            crossing_indices[joint_id] = sequence.index(frame_id)
        joint = joints[joint_id];parent = frames[joint['parent']]
        origin = robot.transform(parent, _vector(joint['frame']['origin'], values))
        axis = hose._unit(_direction(parent, _vector(joint['frame']['axis'], values)))
        delta = hose._sub(point, origin)
        radial = hose._sub(delta, hose._mul(axis, hose._dot(delta, axis)))
        crossings[joint_id] = {'frame_id': frame_id, 'point_mm': point,
                               'axis_origin_mm': origin, 'axis_direction': axis,
                               'radial_standoff_mm': math.sqrt(hose._dot(radial, radial))}
    path['framed_crossings'] = crossings
    path['crossing_control_indices'] = crossing_indices
    inserted = sum(row['length_mm'] for row in parts if row['kind'] == 'inserted')
    strain = sum(row['length_mm'] for row in parts if row['kind'] == 'socket_strain_relief')
    straight = sum(row['length_mm'] for row in parts if row['kind'] == 'connector_straight_lead')
    clips = sum(row['length_mm'] for row in parts if row['kind'] == 'clip_straight')
    bare = sum(row['length_mm'] for row in parts if row['kind'] == 'bare_span')
    accounted = inserted+strain+straight+clips+bare+guide_path['length_mm']
    if abs(accounted-path['length_mm']) > 1e-7:
        raise ValueError('Inserted, supported and free tube lengths do not sum to the full cut')
    path['length_accounting'] = {'inserted_mm': inserted, 'socket_strain_relief_mm': strain,
        'connector_straight_leads_mm': straight, 'clip_supported_mm': clips,
        'carrier_supported_mm': guide_path['length_mm'], 'free_bare_spans_mm': bare,
        'external_guide_straights_included_in_free_mm': sum(external),
        'total_mm': path['length_mm'], 'sum_error_mm': accounted-path['length_mm'],
        'service_loop_parameter_mm': slack, 'parts': parts,
        'scope': 'All tube material, including both insertions, counted once; the service-loop coordinate '
                 'changes free-span shape and is not another length added to this sum'}
    return path


def _reported_length(path):
    if not isinstance(path, dict) or path.get('format') != 'solidcraftbot.static-hose-centerline/1':
        raise RoutingEvidenceError('Routing evaluator returned an invalid shared path')
    try:
        length = _number(path.get('length_mm'), 'reported route length')
        actual_length = sum(_number(segment.get('length_mm'), 'segment length') for segment in path['segments'])
    except (ValueError, KeyError, TypeError) as error:
        raise RoutingEvidenceError('Routing evaluator returned malformed length evidence') from error
    if length <= 0 or not path.get('segments'):
        raise RoutingEvidenceError('Routing evaluator returned an empty path')
    if abs(actual_length-length) > 1e-7:
        raise RoutingEvidenceError('Reported route length differs from its exact segments')
    return length


def _check_route(name, path, p, clearance_check, self_sample_step_mm, slack):
    _reported_length(path)
    hose._joined_path(path)
    for index, segment in enumerate(path['segments']):
        if segment['kind'] == 'arc' and segment['radius_mm'] < p['hoseBendRadius']-1e-9:
            raise hose.HoseBendError('Bare-hose hard radius is not met',
                {'segment_index': index, 'achieved_radius_mm': segment['radius_mm'],
                 'required_radius_mm': p['hoseBendRadius']})
    guide = path['carrier_path']
    if guide['min_bend_radius_mm'] is not None and guide['min_bend_radius_mm'] < 50-1e-9:
        raise hose.HoseBendError('Guide hard radius is not met',
            {'achieved_radius_mm': guide['min_bend_radius_mm'], 'required_radius_mm': 50})
    self_check = hose.self_clearance_diagnostics(path, p['hoseOuterRadius'], self_sample_step_mm)
    if not self_check['passed']:
        return {'passed': False, 'classification': 'self_crossing', 'self_clearance': self_check}
    if clearance_check is None:
        return {'passed': False, 'classification': 'clearance_not_evaluated', 'self_clearance': self_check}
    clearance = clearance_check(path, name, slack)
    if not isinstance(clearance, dict) or type(clearance.get('passed')) is not bool or not clearance.get('scope'):
        raise ValueError('A clearance callback must report a boolean result and its evidence scope')
    json.dumps(clearance, allow_nan=False)
    return {'passed': clearance['passed'], 'classification': 'feasible' if clearance['passed'] else 'clearance',
            'self_clearance': self_check, 'external_clearance': clearance}


def compile_named_band(named_states, evaluate_route, loop_samples_mm, *, p, clearance_check,
                       allowances, cut_resolution_mm=1.0, self_sample_step_mm=.5):
    """Demonstrate one common cut at named static states; never certify a hull.

    Loop samples classify geometry, self-clearance and the supplied independent
    clearance evidence. Their extrema are a diagnostic length hull only. The
    selected cut is solved and checked separately at every state, so gaps and
    nonmonotonic length curves cannot be hidden by the hull's endpoints.
    """
    names = list(named_states)
    if not names or len(set(names)) != len(names) or any(not isinstance(n, str) or not n for n in names):
        raise ValueError('Named routing states must have unique nonempty names')
    loops = sorted(set(_number(v, 'loop sample', True) for v in loop_samples_mm))
    if len(loops) < 2:
        raise ValueError('A finite band study needs at least two distinct loop samples')
    resolution = _number(cut_resolution_mm, 'cut resolution')
    if resolution <= 0:
        raise ValueError('Cut resolution must be positive')
    _number(self_sample_step_mm, 'self-clearance sample step')
    if self_sample_step_mm <= 0:
        raise ValueError('Self-clearance sample step must be positive')
    items = []
    ids = set()
    for row in allowances:
        if (not isinstance(row, dict) or set(row) != {'id', 'value_mm', 'reason'}
                or not isinstance(row['id'], str) or not row['id'] or row['id'] in ids
                or not isinstance(row['reason'], str) or not row['reason']):
            raise ValueError('Each cutting allowance needs a unique id, value_mm and reason')
        ids.add(row['id'])
        items.append({**row, 'value_mm': _number(row['value_mm'], 'allowance', True)})
    rows, feasible_paths = {}, {}
    for name in names:
        samples, eligible = [], []
        for value in loops:
            try:
                path = evaluate_route(name, value)
            except RoutingEvidenceError:
                raise
            except hose.HoseBendError as error:
                sample = {'loop_parameter_mm': value, 'passed': False, 'classification': 'bend',
                          'error': str(error), 'witness': error.witness}
            except RouteClearanceError as error:
                sample = {'loop_parameter_mm': value, 'passed': False, 'classification': 'clearance',
                          'error': str(error), 'witness': error.witness}
            except ValueError as error:
                sample = {'loop_parameter_mm': value, 'passed': False, 'classification': 'route_infeasible',
                          'error': str(error)}
            else:
                check = _check_route(name, path, p, clearance_check, self_sample_step_mm, value)
                sample = {'loop_parameter_mm': value, 'length_mm': path['length_mm'], **check}
                if check['passed']:
                    eligible.append(sample)
                    feasible_paths[(name, value)] = path
            samples.append(sample)
        low = min(eligible, key=lambda row: row['length_mm']) if eligible else None
        high = max(eligible, key=lambda row: row['length_mm']) if eligible else None
        runs, current = [], []
        for index, sample in enumerate(samples):
            if sample['passed']:
                current.append(index)
            elif current:
                runs.append(current);current = []
        if current:
            runs.append(current)
        rows[name] = {'samples': samples, 'feasible_sample_count': len(eligible),
                      'demonstrated_min': low, 'demonstrated_max': high,
                      'consecutive_passed_sample_runs': [
                          {'sample_indices': run,
                           'loop_parameter_hull_mm': [samples[run[0]]['loop_parameter_mm'], samples[run[-1]]['loop_parameter_mm']],
                           'sampled_length_hull_mm': [min(samples[i]['length_mm'] for i in run),
                                                       max(samples[i]['length_mm'] for i in run)]}
                          for run in runs],
                      'runs_scope': 'Consecutive passed samples only; rejected samples split runs. '
                                    'Unsampled loop values are not verified, even within one run.'}
    complete = all(row['demonstrated_min'] is not None for row in rows.values())
    lower = max(row['demonstrated_min']['length_mm'] for row in rows.values()) if complete else None
    upper = min(row['demonstrated_max']['length_mm'] for row in rows.values()) if complete else None
    common = complete and lower <= upper
    requested = lower+sum(row['value_mm'] for row in items) if complete else None
    cut = math.ceil((requested-1e-9)/resolution)*resolution if requested is not None else None
    rounding = cut-requested if cut is not None else None
    selected, failures = {}, []
    if not common:
        failures.append({'classification': 'no_common_demonstrated_hull'})
    elif cut > upper+1e-7:
        failures.append({'classification': 'cut_above_demonstrated_hull', 'cut_mm': cut, 'upper_mm': upper})
    else:
        for name, row in rows.items():
            chosen = None
            for sample in row['samples']:
                if sample['passed'] and abs(sample['length_mm']-cut) <= 1e-7:
                    chosen = (sample['loop_parameter_mm'], feasible_paths[(name, sample['loop_parameter_mm'])], sample)
                    break
            if chosen is None:
                for left, right in zip(row['samples'], row['samples'][1:]):
                    if (not left['passed'] or not right['passed']
                            or (left['length_mm']-cut)*(right['length_mm']-cut) > 0):
                        continue
                    lo, hi = left['loop_parameter_mm'], right['loop_parameter_mm']
                    base_sign = left['length_mm']-cut
                    try:
                        for _ in range(45):
                            mid = (lo+hi)/2;path = evaluate_route(name, mid)
                            if (_reported_length(path)-cut)*base_sign > 0:lo = mid
                            else:hi = mid
                        value = (lo+hi)/2;path = evaluate_route(name, value)
                    except RoutingEvidenceError:
                        raise
                    except ValueError:
                        continue
                    check = _check_route(name, path, p, clearance_check, self_sample_step_mm, value)
                    if check['passed'] and abs(path['length_mm']-cut) <= 1e-7:
                        chosen = (value, path, check)
                        break
            if chosen is None:
                failures.append({'state': name, 'classification': 'selected_cut_not_demonstrated'})
                continue
            value, path, check = chosen
            partition = path['length_accounting']
            physical = sum(partition[key] for key in ('inserted_mm', 'socket_strain_relief_mm',
                'connector_straight_leads_mm', 'clip_supported_mm', 'carrier_supported_mm', 'free_bare_spans_mm'))
            if abs(physical-cut) > 1e-7 or abs(partition['total_mm']-cut) > 1e-7:
                raise ValueError('Selected route material partition does not sum to the cut')
            selected[name] = {'loop_parameter_mm': value, 'length_mm': path['length_mm'],
                'material_partition': partition, 'route': path, 'checks': check,
                'extra_material_over_demonstrated_min_mm': cut-row['demonstrated_min']['length_mm']}
    return {'format': 'solidcraftbot.framed-hose-length-band/1',
        'status': 'demonstrated' if not failures and len(selected) == len(names) else 'blocked',
        'scope': 'Minimum demonstrated under stated source-frame, finite loop-sampling and clearance assumptions; '
                 'named static configurations only, not an exact global minimum or maximum.',
        'states': rows, 'loop_samples_mm': loops,
        'common_band': {'lower_mm': lower, 'upper_mm': upper, 'nonempty': common,
            'scope': 'Intersection of sampled feasible-length hulls only; gaps, intermediate feasibility '
                     'and continuous reachability are not verified by these endpoints.'},
        'cut_selection': {'max_demonstrated_min_mm': lower, 'allowances': items,
            'allowance_total_mm': sum(row['value_mm'] for row in items),
            'before_rounding_mm': requested, 'cut_resolution_mm': resolution,
            'rounding_allowance_mm': rounding, 'rounding_reason': 'Round the physical cut upward to the declared cutting increment',
            'selected_cut_mm': cut,
            'scope': 'Selection allowances explain extra loop material above demonstrated minima; '
                     'nominal insertions/supports already belong to each physical route and are not added twice.'},
        'selected_states': selected, 'failures': failures,
        'qualification': {'continuous_loop_reachability_verified': False, 'global_optimum_verified': False,
                          'full_joint_window_clearance_verified': False, 'hardware_execution_implemented': False}}
