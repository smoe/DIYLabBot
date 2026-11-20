"""Sample hose-length brackets on a declared arm window, without CAD or motion claims.

Only the shared route_at operation evaluates geometry. Corners and subdivided
edges are finite samples, not a search over the interior or a clearance proof.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import arm_syringe


ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.arm-syringe-window-scan/1'


def _number(value, name, *, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (value <= 0 if positive else value < 0)):
        raise ValueError(name+' must be a finite '+('positive' if positive else 'nonnegative')+' number')
    return float(value)


def _canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _pins(spec):
    paths = [Path(__file__), ROOT/'scripts/arm_syringe.py', ROOT/'scripts/pneumatic_hose.py',
             ROOT/'scripts/robot_spec.py', ROOT/'scripts/syringe_pipette.py',
             ROOT/'model/arm-syringe.schema.json']
    paths += arm_syringe.source_dependencies(spec)
    for key in ('robot', 'syringe_library', 'hose_carrier'):
        if spec.get(key) is not None:
            paths.append(ROOT/spec[key]['source'])
    files = {}
    for path in paths:
        resolved = path.resolve()
        files[str(resolved.relative_to(ROOT))] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return {'files_sha256': files, 'evaluated_source_canonical_sha256': _canonical_sha(spec)}


def _configuration(spec, window, max_step_deg, margin_mm, max_slack_mm):
    arm = arm_syringe.arm(spec)
    joints = arm['joints']
    ids = [joint['id'] for joint in joints]
    if len(ids) != 6 or len(set(ids)) != 6:
        raise ValueError('A six-axis robot with unique source joint IDs is required')
    if not isinstance(window, dict) or set(window) != set(ids):
        raise ValueError('The operating window must name exactly the six source joints')
    checked = {}
    for joint in joints:
        name = joint['id']
        row = window[name]
        if (not isinstance(row, dict) or set(row) != {'range', 'reason'}
                or not isinstance(row['reason'], str) or not row['reason'].strip()
                or not isinstance(row['range'], list) or len(row['range']) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in row['range'])):
            raise ValueError('A finite range and explicit reason are required for '+name)
        lo, hi = row['range']
        limits = joint['limits_deg']
        if not limits[0] <= lo <= hi <= limits[1]:
            raise ValueError('Operating window exceeds source limits for '+name)
        checked[name] = {'range': [float(lo), float(hi)], 'reason': row['reason'],
                         'source_limits_deg': list(limits), 'source_frame': joint['frame'],
                         'parent': joint['parent'], 'child': joint['child']}
    return ids, checked, {
        'scan_max_step_deg': _number(max_step_deg, 'scan_max_step_deg', positive=True),
        'margin_mm': _number(margin_mm, 'margin_mm'),
        'max_service_loop_mm': _number(max_slack_mm, 'max_service_loop_mm', positive=True)}


def _samples(spec, ids, window, max_step):
    """Preserve all edge memberships while evaluating each coordinate only once."""
    samples = {}
    ranges = [window[name]['range'] for name in ids]
    endpoints = [tuple(dict.fromkeys(pair)) for pair in ranges]

    def add(q, *, corner=False, edge=None, state=None):
        key = tuple(float(value) for value in q)
        if key not in samples:
            samples[key] = {'joints_deg': list(key), 'joints_by_id_deg': dict(zip(ids, key)),
                            'corner': False, 'edges': [], 'named_states': [],
                            'inside_window': all(lo <= value <= hi for value, (lo, hi)
                                                 in zip(key, ranges))}
        row = samples[key]
        row['corner'] |= corner
        if edge is not None:
            row['edges'].append(edge)
        if state is not None:
            row['named_states'].append(state)

    for q in itertools.product(*endpoints):
        add(q, corner=True)
    edges = []
    for axis, (lo, hi) in enumerate(ranges):
        if lo == hi:
            continue
        count = math.ceil((hi-lo)/max_step)
        fixed_axes = [i for i in range(len(ids)) if i != axis]
        for fixed in itertools.product(*(endpoints[i] for i in fixed_axes)):
            edge_id = 'edge_'+str(len(edges)+1).zfill(3)
            q = [0.0]*len(ids)
            for index, value in zip(fixed_axes, fixed):
                q[index] = value
            edges.append({'id': edge_id, 'joint_id': ids[axis], 'range_deg': [lo, hi],
                          'fixed_joints_deg': {ids[i]: q[i] for i in fixed_axes},
                          'intervals': count, 'sample_count': count+1,
                          'step_deg': (hi-lo)/count})
            for i in range(count+1):
                # Avoid a floating-point extrapolation beyond either endpoint.
                q[axis] = lo if i == 0 else hi if i == count else lo+(hi-lo)*i/count
                add(q, edge=edge_id)
    for name, state in spec['states'].items():
        q = state['joints_deg']
        if (not isinstance(q, list) or len(q) != len(ids)
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in q)
                or any(not window[joint]['source_limits_deg'][0] <= value
                       <= window[joint]['source_limits_deg'][1] for joint, value in zip(ids, q))):
            raise ValueError('Named state exceeds source joint contract: '+name)
        add(q, state=name)
    return list(samples.values()), edges


def scan(spec, p, window=None, *, max_step_deg=None, margin_mm=None,
         max_slack_mm=None, route_at=None, named_band=None):
    """Return finite corner/edge and named-state route-length measurements.

    Every distinct joint coordinate makes exactly two geometry calls: zero
    service-loop extension and the configured maximum. Named states outside
    the window are retained and constrain the suggested length explicitly.
    Exceptions are preserved per endpoint; incomplete scans give no proposal.
    """
    if route_at is None and 'hose_routing' in spec:
        raise ValueError('The link-clipped hose fixes material at each clip; '
                         'use prepare_arm_hose_routing.py instead of a global scalar scan')
    design = spec.get('hose_length_design', {})
    source_design = design
    physical = 'allowances' in design
    window = spec.get('operating_window_deg') if window is None else window
    max_step_deg = design.get('scan_max_step_deg', 30) if max_step_deg is None else max_step_deg
    default_margin = sum(item['value_mm'] for item in design['allowances']) if physical else design.get('margin_mm', 10)
    margin_mm = default_margin if margin_mm is None else margin_mm
    max_slack_mm = design.get('max_service_loop_mm', 200) if max_slack_mm is None else max_slack_mm
    pins = _pins(spec)
    ids, checked, design = _configuration(spec, window, max_step_deg, margin_mm, max_slack_mm)
    if physical:
        design.update({key: value for key, value in source_design.items() if key not in design})
        design['margin_origin'] = 'Derived sum of itemized source cutting allowances; not another physical length'
    selected = _number(p['hoseLength'], 'hoseLength', positive=True)
    samples, edges = _samples(spec, ids, checked, design['scan_max_step_deg'])
    context = None
    if route_at is None:
        context = arm_syringe.prepare_route_context(spec, p)

        def evaluator(source, parameters, joints, slack):
            return arm_syringe.route_at(source, parameters, joints, slack, context=context)
    else:
        evaluator = route_at
        if physical:
            context = arm_syringe.prepare_route_context(spec, p)
    errors, unsupported = [], []
    for index, row in enumerate(samples):
        row['id'] = 'sample_'+str(index+1).zfill(4)
        row['endpoints'] = {}
        for label, slack in (('zero_slack', 0.0), ('max_service_loop', design['max_service_loop_mm'])):
            try:
                path = evaluator(spec, p, list(row['joints_deg']), slack)
            except Exception as exc:
                error = {'sample_id': row['id'], 'endpoint': label,
                         'error_type': type(exc).__name__, 'message': str(exc)}
                row['endpoints'][label] = {'service_loop_mm': slack, 'error': error}
                if (physical and isinstance(exc, ValueError)
                        and not isinstance(exc, arm_syringe.routing.RoutingEvidenceError)):
                    classification = ('bend' if isinstance(exc, arm_syringe.pneumatic_hose.HoseBendError)
                                      else 'envelope_proximity' if isinstance(exc, arm_syringe.routing.RouteClearanceError)
                                      else 'route_infeasible')
                    error['classification'] = classification
                    error['witness'] = getattr(exc, 'witness', None)
                    unsupported.append(error)
                else:
                    errors.append(error)
                continue
            try:
                length = _number(path['length_mm'], 'route length', positive=True)
                endpoint = {'service_loop_mm': slack, 'length_mm': length}
                if physical:
                    self_check = arm_syringe.pneumatic_hose.self_clearance_diagnostics(path, p['hoseOuterRadius'])
                    frames, mounted = arm_syringe._placements(spec, p, row['joints_deg'], spec['default_state'], context)
                    external = arm_syringe._route_clearance(spec, p, path, frames, mounted, context)
                    endpoint['checks'] = {'self_clearance': self_check, 'source_clearance': external}
                    if not self_check['passed'] or not external['passed']:
                        classification = 'self_crossing' if not self_check['passed'] else 'envelope_proximity'
                        endpoint['unsupported_classification'] = classification
                        unsupported.append({'sample_id': row['id'], 'endpoint': label,
                                            'classification': classification, 'checks': endpoint['checks']})
                row['endpoints'][label] = endpoint
            except Exception as exc:
                error = {'sample_id': row['id'], 'endpoint': label,
                         'error_type': type(exc).__name__, 'message': str(exc)}
                row['endpoints'][label] = {'service_loop_mm': slack, 'error': error}
                errors.append(error)
        values = row['endpoints']
        if all('length_mm' in values[key] for key in ('zero_slack', 'max_service_loop')):
            low = values['zero_slack']['length_mm']
            high = values['max_service_loop']['length_mm']
            row['endpoint_order_valid'] = high >= low
            row['selected_length_within_endpoint_bracket'] = low <= selected <= high
            row['classification'] = ('nonmonotonic_endpoint_lengths' if high < low else
                'too_short_for_endpoint_bracket' if selected < low else
                'too_long_for_endpoint_bracket' if selected > high else 'inside_endpoint_length_bracket')
            if high < low:
                error = {'sample_id': row['id'], 'endpoint': 'both',
                         'error_type': 'ReversedLengthBracket',
                         'message': 'Maximum service-loop endpoint is shorter than zero-slack endpoint'}
                if physical:
                    error['classification'] = 'nonmonotonic_endpoint_lengths'
                (unsupported if physical else errors).append(error)
                row['bracket_error'] = error
        else:
            row['endpoint_order_valid'] = False
            row['selected_length_within_endpoint_bracket'] = None
            row['classification'] = 'route_unavailable_at_diagnostic_endpoint'

    def extreme(label, longest):
        available = [row for row in samples if 'length_mm' in row['endpoints'][label]]
        if not available:
            return None
        result = (max if longest else min)(available,
                   key=lambda row: row['endpoints'][label]['length_mm'])
        return {key: result[key] for key in ('id', 'joints_deg', 'joints_by_id_deg',
                                              'named_states', 'inside_window')} | {
            'length_mm': result['endpoints'][label]['length_mm'],
            'endpoint_unsupported_classification': result['endpoints'][label].get('unsupported_classification'),
            'scope': 'Diagnostic endpoint extrema; not a selected-cut or whole-robot operating-state proof'}

    extrema = {label: {'shortest': extreme(label, False), 'longest': extreme(label, True)}
               for label in ('zero_slack', 'max_service_loop')}
    band = None
    if named_band is not None:
        band = named_band(spec, p) if callable(named_band) else named_band
    elif physical:
        band = arm_syringe.named_length_band(spec, p, context=context)
    if band is not None and band['status'] != 'demonstrated':
        errors.append({'sample_id': None, 'endpoint': None, 'error_type': 'NamedBandBlocked',
                       'message': 'One or more required named states has no independently demonstrated common cut',
                       'failures': band['failures']})
    unchanged = pins == _pins(spec)
    if not unchanged:
        errors.append({'sample_id': None, 'endpoint': None, 'error_type': 'SourceChangedDuringScan',
                       'message': 'A pinned source file changed while route endpoints were evaluated'})
    complete = not errors
    bracket = None
    suggestion = None
    if complete and not unsupported:
        lo = extrema['zero_slack']['longest']['length_mm']
        hi = extrema['max_service_loop']['shortest']['length_mm']
        suggestion = math.ceil(lo+design['margin_mm'])
        bracket = {'min_length_mm': lo, 'max_length_mm': hi, 'nonempty': lo <= hi,
                   'selected_length_mm': selected, 'selected_within': lo <= selected <= hi,
                   'suggested_length_mm': suggestion, 'suggested_within': lo <= suggestion <= hi}
    if band is not None:
        suggestion = band['cut_selection']['selected_cut_mm'] if complete and band['status'] == 'demonstrated' else None
    out_of_window = [name for row in samples if not row['inside_window'] for name in row['named_states']]
    return {
        'format': FORMAT,
        'scope': ('Classified finite corner/edge diagnostics plus independently checked named-state cut design'
                  if physical else 'Finite corner/edge and named-state length samples; two service-loop endpoints only'),
        'joint_order': ids, 'operating_window_deg': checked,
        'operating_window_status': spec.get('operating_window_status', 'Unqualified design assumption'),
        'hose_length_design': design, 'parameters': dict(p),
        'sample_coverage': {'unique_joint_coordinates': len(samples),
                            'corner_count': sum(row['corner'] for row in samples),
                            'edge_count': len(edges), 'route_endpoint_calls': 2*len(samples),
                            'named_state_count': len(spec['states']),
                            'named_states_outside_window': out_of_window,
                            'extrema_scope': 'Union of sampled window corners/edges and all named states',
                            'unsupported_endpoint_observations': len(unsupported),
                            'named_state_support_complete': band is not None and band['status'] == 'demonstrated',
                            'complete': complete},
        'edges': edges, 'samples': samples, 'errors': errors, 'extrema': extrema,
        'diagnostic_unsupported': unsupported, 'named_state_band': band,
        'common_endpoint_bracket': bracket, 'suggested_hose_length_mm': suggestion,
        'qualification': {'full_window_continuous_verified': False,
                          'interior_extrema_verified': False,
                          'intermediate_service_loop_reachability_verified': False,
                          'collision_clearance_verified': False,
                          'material_bend_radius_verified': False,
                          'pressure_flow_or_dosing_verified': False},
        'source_pins': pins, 'source_files_unchanged_during_scan': unchanged,
        'scan_input_canonical_sha256': _canonical_sha({'window': checked, 'design': design, 'parameters': p})}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=arm_syringe.SOURCE)
    parser.add_argument('--output', type=Path, default=ROOT/'exports/arm-syringe/window-scan.json')
    parser.add_argument('--max-step-deg', type=float)
    parser.add_argument('--margin-mm', type=float)
    parser.add_argument('--max-slack-mm', type=float)
    args = parser.parse_args(argv)
    source_digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
    spec = arm_syringe.load(args.source)
    report = scan(spec, arm_syringe.parameters(spec), max_step_deg=args.max_step_deg,
                  margin_mm=args.margin_mm, max_slack_mm=args.max_slack_mm)
    report['source_file'] = str(args.source.resolve())
    report['source_file_sha256'] = source_digest
    report['source_file_unchanged_during_scan'] = source_digest == hashlib.sha256(args.source.read_bytes()).hexdigest()
    if not report['source_file_unchanged_during_scan']:
        report['errors'].append({'sample_id': None, 'endpoint': None, 'error_type': 'SourceChangedDuringScan',
                                 'message': 'The arm-syringe source file changed during this scan'})
        report['sample_coverage']['complete'] = False
        report['common_endpoint_bracket'] = None
        report['suggested_hose_length_mm'] = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(str(args.output.resolve()))
    return 0 if report['sample_coverage']['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
