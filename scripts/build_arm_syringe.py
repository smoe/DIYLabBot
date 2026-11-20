"""Build the dedicated syringe arm from a checked native arm and shared tooling.

Each CAD backend reuses only its own checked arm artifact.  The resulting
assembly remains a geometric concept, not a qualified pipette or perfusor.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from build_instrument_concepts import freecad_environment
import robot_spec as robot
import tool_paths


CONTACT_DISTANCE_TOLERANCE_MM = 1e-7
OVERLAP_ZERO_TOLERANCE_MM3 = 1e-5


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def checked_arm_cache(report_path, backend, root):
    """Check current source pins and exactly the requested backend artifact."""
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if backend not in {'freecad', 'solidcraft'}:
        raise ValueError('Choose one native arm backend')
    source_path = Path(root)/report.get('spec', 'model/robot.json')
    if not report.get('passed') or report.get('spec_sha256') != digest(source_path):
        raise ValueError('Arm cache is failed or bound to another robot revision')
    for key in ('generator_sha256', 'vendor_source_sha256'):
        pins = report.get(key)
        if not isinstance(pins, dict) or not pins:
            raise ValueError('Arm cache lacks '+key)
        for name, checksum in pins.items():
            path = (Path(root)/name).resolve()
            if not path.is_relative_to(Path(root).resolve()) or digest(path) != checksum:
                raise ValueError('Current arm dependency differs: '+name)
    relative = Path(report['artifacts'][backend])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Arm artifact path must remain relative to its build root')
    candidates = [parent for parent in report_path.parents
                  if (parent/report.get('spec', 'model/robot.json')).is_file()
                  and (parent/relative).is_file()]
    if not candidates:
        raise ValueError('Cannot resolve the checked native arm artifact')
    cache_root = candidates[0]
    artifact = cache_root/relative
    if digest(artifact) != report['artifact_sha256'][backend]:
        raise ValueError('Native arm bytes differ from their checked report')
    return {'backend': backend, 'path': str(artifact),
            'sha256': report['artifact_sha256'][backend],
            'report_path': str(report_path), 'report_sha256': digest(report_path),
            'spec_sha256': report['spec_sha256'],
            'aliases': report.get('solidcraft_body_aliases', {}),
            'generator_sha256': report['generator_sha256'],
            'vendor_source_sha256': report['vendor_source_sha256']}


def arm_bodies(arm):
    return [{'id': op['body'], 'group': link['id'], 'role': op['role']}
            for link in robot.expanded(arm)['links'] for op in link['recipe']
            if op['action'] == 'create']


def carrier_bodies(state):
    """Two delivered semantic representations; the filled guard is check-only."""
    record = state.get('carrier')
    if record is None:
        return []
    count = record['nominal_link_count']
    if (type(count) is not int or count <= 0 or len(record['links']) != count
            or record['native_aliases'] != [row['id'] for row in record['links']]
            or len(set(record['native_aliases'])) != count):
        raise ValueError('Carrier collar records have inconsistent identities or count')
    return [
        {'id': 'CarrierEnvelope', 'component': 'CarrierSnapshot',
         'role': 'static_concept_carrier_shell', 'expected_solid_count': 1,
         'appearance': {'color': '#668d71', 'opacity': .15}},
        {'id': 'CarrierLinks', 'component': 'CarrierSnapshot',
         'role': 'static_nominal_carrier_collars', 'expected_solid_count': count,
         'appearance': {'color': '#252a30', 'opacity': 1}},
    ]


def carrier_aliases(state):
    return {'CarrierLinks': state['carrier']['native_aliases']} if carrier_bodies(state) else {}


def guard_pair_groups(arm_meta, rigid_meta):
    """The filled reservation is checked against external physical objects only."""
    return {'carrier_guard_arm': [('CarrierOuterGuard', row['id']) for row in arm_meta
                                  if row['role'] != 'viewing_cone'],
            'carrier_guard_tooling': [('CarrierOuterGuard', row['id']) for row in rigid_meta]}


def merge_clearance_checks(material, guard):
    """Keep guard/contents classification separate from allowed material contact."""
    categories = {**material['categories'], **guard['categories']}
    observed = [(row['minimum_distance_mm'], row['closest_pair'])
                for row in categories.values() if row['minimum_distance_mm'] is not None]
    minimum, closest = min(observed, key=lambda row: row[0]) if observed else (None, None)
    return {**material, 'passed': material['passed'] and guard['passed'],
            'categories': categories,
            'checked_pairs': material['checked_pairs']+guard['checked_pairs'],
            'exact_distance_checks': material['exact_distance_checks']+guard['exact_distance_checks'],
            'minimum_nonallowed_distance_mm': minimum, 'closest_pair': closest,
            'interferences': material['interferences']+guard['interferences'],
            'undeclared_contacts': material['undeclared_contacts']+guard['undeclared_contacts'],
            'zero_distance_pairs': material['zero_distance_pairs']+guard['zero_distance_pairs'],
            'clearance_proxy_policy': {
                'id': 'CarrierOuterGuard', 'representation': 'filled_outside_reservation',
                'delivered_material_body': False,
                'external_classes_checked': ['physical_arm_and_cameras', 'rigid_tooling'],
                'contained_representation_classes': ['routed_hose', 'carrier_shell', 'nominal_carrier_collars'],
                'scope': 'Expected contents are not guard collision pairs; actual carrier material remains '
                         'collision-checked against the hose, and collar containment is checked separately'}}


def pneumatic_connections(clearances, interfaces=None, socket_mating=None):
    """A coincident face alone cannot certify an inserted socket connection."""
    if not isinstance(interfaces, dict) or set(interfaces) != {'pump', 'tip'}:
        raise ValueError('Both source-defined tube-in-socket interfaces are required')
    expected = {row['body'] for row in interfaces.values()}
    rows = {}
    for row in clearances['allowed_contacts']:
        if 'PneumaticHose' in (row['a'], row['b']):
            other = row['b'] if row['a'] == 'PneumaticHose' else row['a']
            if other in expected:
                rows[other] = row
    native_ok = (isinstance(socket_mating, dict) and socket_mating.get('passed') is True
                 and set(socket_mating.get('interfaces', {})) == set(interfaces)
                 and all(row.get('passed') is True for row in socket_mating['interfaces'].values()))
    return {'passed': native_ok and set(rows) == expected and all(
                row['distance_mm'] <= CONTACT_DISTANCE_TOLERANCE_MM
                and row['overlap_mm3'] <= OVERLAP_ZERO_TOLERANCE_MM3 for row in rows.values()),
            'required_interfaces': sorted(interfaces), 'required_bodies': sorted(expected),
            'observations': rows, 'socket_mating': socket_mating,
            'distance_tolerance_mm': CONTACT_DISTANCE_TOLERANCE_MM,
            'scope': 'Inserted coaxial tube ends, positive OD clearance and declared floor contacts; '
                     'compression retention, insertion force and gas tightness remain unqualified'}


def require_hose_self_clearance(state):
    diagnostic = state.get('hose_self_clearance')
    if (not isinstance(diagnostic, dict) or diagnostic.get('passed') is not True
            or diagnostic.get('continuous_self_clearance_verified') is not False):
        raise ValueError('A passed finite hose self-clearance diagnostic is required; continuous clearance remains unqualified')
    return diagnostic


MATERIAL_LENGTH_KEYS = ('inserted_mm', 'socket_strain_relief_mm', 'connector_straight_leads_mm',
                        'clip_supported_mm', 'carrier_supported_mm', 'free_bare_spans_mm')


def route_material_checks(path, parameters):
    """Validate achieved geometry and a nonduplicated physical tube partition."""
    import pneumatic_hose
    pneumatic_hose._path(path)
    pneumatic_hose._joined_path(path)
    required = parameters['hoseBendRadius']
    if type(required) not in (int, float) or not math.isfinite(required) or required < 12:
        raise ValueError('The provisional bare-hose hard radius must be at least12 mm')
    segments = path['segments']
    for segment in segments:
        for key in ('start_mm', 'end_mm'):pneumatic_hose._point(segment[key])
        if (type(segment['length_mm']) not in (int, float)
                or not math.isfinite(segment['length_mm']) or segment['length_mm'] <= 0):
            raise ValueError('Exact route segments need positive finite lengths')
        if segment['kind'] == 'arc':
            if (type(segment['radius_mm']) not in (int, float) or not math.isfinite(segment['radius_mm'])
                    or segment['radius_mm'] <= 0):
                raise ValueError('Exact arc radii must be positive and finite')
        elif segment['kind'] != 'line':
            raise ValueError('Only exact line and arc route segments are supported')
    account = path['length_accounting']
    coverage = [0]*len(segments)
    bare_radii = []
    ids = set()
    roles = {'inserted': 'inserted_mm', 'socket_strain_relief': 'socket_strain_relief_mm',
             'connector_straight_lead': 'connector_straight_leads_mm', 'clip_straight': 'clip_supported_mm',
             'nominal_carrier': 'carrier_supported_mm', 'bare_span': 'free_bare_spans_mm'}
    totals = {key: 0. for key in MATERIAL_LENGTH_KEYS}
    for part in account['parts']:
        if not isinstance(part['id'], str) or not part['id'] or part['id'] in ids:
            raise ValueError('A physical material span is counted more than once')
        ids.add(part['id'])
        start, count = part['segment_start_index'], part['segment_count']
        if type(start) is not int or type(count) is not int or count <= 0 or start < 0 or start+count > len(segments):
            raise ValueError('Invalid material-span segment coverage')
        selected = segments[start:start+count]
        if (type(part['length_mm']) not in (int, float) or not math.isfinite(part['length_mm'])
                or abs(sum(row['length_mm'] for row in selected)-part['length_mm']) > 1e-7):
            raise ValueError('A physical material span differs from its exact segment lengths')
        for index in range(start, start+count):coverage[index] += 1
        if part['kind'] == 'bare_span':
            bare_radii.extend(row['radius_mm'] for row in selected if row['kind'] == 'arc')
        elif part['kind'] not in roles:
            raise ValueError('Unsupported physical material-span role')
        if part['kind'] not in ('bare_span', 'nominal_carrier') and any(row['kind'] != 'line' for row in selected):
            raise ValueError('Inserted and supported straight material cannot contain a bend')
        totals[roles[part['kind']]] += part['length_mm']
    if any(value != 1 for value in coverage):
        raise ValueError('Every tube segment must belong to exactly one physical material span')
    guide = path['carrier_path']
    guide_parts = [part for part in account['parts'] if part['kind'] == 'nominal_carrier']
    if len(guide_parts) != 1:
        raise ValueError('One exact nominal carrier material span is required')
    guide_part = guide_parts[0]
    guide_start = guide_part['segment_start_index']
    guide_end = guide_start+guide_part['segment_count']
    if not compare_derived_metrics(guide['segments'], segments[guide_start:guide_end], tolerance=1e-7)['passed']:
        raise ValueError('The protected guide and its material span have different geometry')

    def straight_run(rows):
        direction = None;length = 0.
        for row in rows:
            if row['kind'] != 'line':break
            delta = pneumatic_hose._sub(row['end_mm'], row['start_mm'])
            current = pneumatic_hose._unit(delta)
            if direction is not None and pneumatic_hose._dot(direction, current) < 1-1e-10:break
            direction = current;length += row['length_mm']
        return length

    internal = guide.get('carrier_fit', {}).get('endpoint_straights_mm')
    minimum_lead = parameters['connectorStraightLead']
    if (not isinstance(internal, list) or len(internal) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   or value < minimum_lead-1e-7 for value in internal)):
        raise ValueError('Both protected guide ends need their declared internal straight leads')
    internal_achieved = [straight_run(guide['segments']), straight_run(list(reversed(guide['segments'])))]
    external_achieved = [straight_run(list(reversed(segments[:guide_start]))),
                         straight_run(segments[guide_end:])]
    # These two real straight pieces are already part of the free material sum.
    before = next((part for part in account['parts']
                   if part['segment_start_index']+part['segment_count'] == guide_start), None)
    after = next((part for part in account['parts'] if part['segment_start_index'] == guide_end), None)
    if (before is None or after is None or before['kind'] != 'bare_span' or after['kind'] != 'bare_span'
            or any(actual < requested-1e-7 for actual, requested in zip(internal_achieved, internal))
            or any(value < minimum_lead-1e-7 for value in external_achieved)
            or abs(account.get('external_guide_straights_included_in_free_mm', -1)-2*minimum_lead) > 1e-7):
        raise ValueError('Both guide transitions require external straight leads counted once as free material')
    guide_straights = {'passed': True, 'internal_required_mm': internal,
        'internal_achieved_mm': internal_achieved, 'external_required_mm': [minimum_lead]*2,
        'external_achieved_mm': external_achieved,
        'external_material_category': 'free_bare_spans_mm',
        'scope': 'Internal leads belong to nominal carrier length; external leads already belong to free spans'}
    guide_radii = [row['radius_mm'] for row in guide['segments'] if row['kind'] == 'arc']
    if any(radius < required-1e-9 for radius in bare_radii) or any(radius < 50-1e-9 for radius in guide_radii):
        raise ValueError('An achieved bare or protected bend violates its hard radius')
    for key in MATERIAL_LENGTH_KEYS:
        if type(account.get(key)) not in (int, float) or not math.isfinite(account[key]) or account[key] < 0:
            raise ValueError('Invalid physical material length: '+key)
        if abs(account[key]-totals[key]) > 1e-7:
            raise ValueError('Material category differs from its exact source span roles: '+key)
    for value in (account['total_mm'], path['length_mm']):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('The complete physical cut must be positive and finite')
    exact = sum(row['length_mm'] for row in segments)
    total = sum(account[key] for key in MATERIAL_LENGTH_KEYS)
    if max(abs(total-exact), abs(account['total_mm']-exact), abs(path['length_mm']-exact),
           abs(exact-parameters['hoseLength'])) > 1e-7:
        raise ValueError('Inserted, supported and free material lengths must sum exactly to the cut')
    expected = {'inserted_mm': 2*parameters['hoseInsertionDepth'],
                'socket_strain_relief_mm': 2*parameters['strainReliefLength'],
                'connector_straight_leads_mm': 2*parameters['connectorStraightLead'],
                'carrier_supported_mm': guide['length_mm']}
    if any(abs(account[key]-value) > 1e-7 for key, value in expected.items()):
        raise ValueError('Socket or guide material support was omitted or counted twice')
    return {'passed': True, 'required_bare_radius_mm': required,
            'achieved_bare_radius_mm': min(bare_radii) if bare_radii else None,
            'required_guide_radius_mm': 50., 'achieved_guide_radius_mm': min(guide_radii) if guide_radii else None,
            'guide_end_straights': guide_straights,
            'exact_segment_length_mm': exact, 'accounted_material_length_mm': total,
            'sum_error_mm': total-exact, 'material_partition': account,
            'scope': 'Achieved static radii and all hose material counted once; no physical bend or motion qualification'}


def validate_named_band(band, spec, parameters):
    """A diagnostic Cartesian hull cannot substitute for named solved routes."""
    names = set(spec['states'])
    if (band.get('format') != 'solidcraftbot.framed-hose-length-band/1'
            or band.get('status') != 'demonstrated' or band.get('failures') != []
            or set(band.get('states', {})) != names or set(band.get('selected_states', {})) != names):
        raise ValueError('A demonstrated solved length witness for every named state is required')
    qualifications = band.get('qualification')
    if not isinstance(qualifications, dict) or not qualifications or any(value is not False for value in qualifications.values()):
        raise ValueError('Finite named-state length evidence cannot claim general qualification')
    minima, maxima = [], []
    for name in names:
        row = band['states'][name]
        eligible = [sample for sample in row['samples'] if sample.get('passed') is True]
        if not eligible:
            raise ValueError('No demonstrated static route for '+name)
        low = min(sample['length_mm'] for sample in eligible)
        high = max(sample['length_mm'] for sample in eligible)
        if (abs(row['demonstrated_min']['length_mm']-low) > 1e-7
                or abs(row['demonstrated_max']['length_mm']-high) > 1e-7):
            raise ValueError('Named length extrema differ from their feasible samples')
        minima.append(low);maxima.append(high)
    lower, upper = max(minima), min(maxima)
    common = band['common_band'];selection = band['cut_selection'];cut = parameters['hoseLength']
    if (common.get('nonempty') is not True or lower > upper
            or abs(common['lower_mm']-lower) > 1e-7 or abs(common['upper_mm']-upper) > 1e-7
            or not lower-1e-7 <= cut <= upper+1e-7 or abs(selection['selected_cut_mm']-cut) > 1e-7):
        raise ValueError('The physical cut is outside the common demonstrated length hull')
    ids = set();allowance_total = 0.
    for allowance in selection['allowances']:
        value = allowance.get('value_mm')
        if (not allowance.get('id') or allowance['id'] in ids or not allowance.get('reason')
                or type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError('Every cutting allowance needs a unique id, finite value and reason')
        ids.add(allowance['id']);allowance_total += value
    before = lower+allowance_total;resolution = selection['cut_resolution_mm']
    if type(resolution) not in (int, float) or not math.isfinite(resolution) or resolution <= 0:
        raise ValueError('A positive finite cutting increment is required')
    rounded = math.ceil((before-1e-9)/resolution)*resolution
    if (abs(selection['max_demonstrated_min_mm']-lower) > 1e-7
            or abs(selection['allowance_total_mm']-allowance_total) > 1e-7
            or abs(selection['before_rounding_mm']-before) > 1e-7
            or abs(selection['rounding_allowance_mm']-(rounded-before)) > 1e-7
            or abs(cut-rounded) > 1e-7):
        raise ValueError('The selected cut is not explained by its itemized allowances and rounding')
    for name, selected in band['selected_states'].items():
        checks = selected['checks']
        if (checks.get('passed') is not True or checks.get('classification') != 'feasible'
                or checks.get('self_clearance', {}).get('passed') is not True
                or checks.get('external_clearance', {}).get('passed') is not True
                or not checks['external_clearance'].get('scope')
                or abs(selected['length_mm']-cut) > 1e-7
                or abs(selected['extra_material_over_demonstrated_min_mm']-
                       (cut-band['states'][name]['demonstrated_min']['length_mm'])) > 1e-7):
            raise ValueError('The selected physical cut was not independently solved and checked at '+name)
        route_material_checks(selected['route'], parameters)
        if selected['material_partition'] != selected['route']['length_accounting']:
            raise ValueError('The selected length witness has two different material partitions')


def bbox_distance(a, b):
    return math.sqrt(sum(max(0., a['min'][i]-b['max'][i], b['min'][i]-a['max'][i])**2
                         for i in range(3)))


def clearance_pair_groups(arm_meta, own_meta):
    """Enumerate physical pairs without excluding any host link or camera."""
    arm_ids = [row['id'] for row in arm_meta if row['role'] != 'viewing_cone']
    own = [*own_meta, {'id': 'PneumaticHose', 'component': 'HoseSnapshot'}]
    tooling = [row for row in own if row['id'] != 'PneumaticHose']
    return {
        'hose_arm': [('PneumaticHose', body) for body in arm_ids],
        'tooling_arm': [(row['id'], body) for row in tooling for body in arm_ids],
        # The hose is another added component in the tooling-to-tooling audit.
        'tooling_tooling': [(a['id'], b['id']) for i, a in enumerate(own)
                            for b in own[i+1:] if a['component'] != b['component']],
    }


def audit_clearances(arm_meta, own_meta, shapes, allowed_contacts, boxes, pair_groups=None):
    """Native shape distances with explicit contacts and category-local bounds.

    This function has no CAD imports so its broad phase and boundary policy can
    also be tested with independent shape witnesses.  ``shapes`` supplies the
    native ``distToShape`` and ``common(...).Volume`` operations.
    """
    pairs = clearance_pair_groups(arm_meta, own_meta) if pair_groups is None else pair_groups
    candidates = {frozenset(pair) for group in pairs.values() for pair in group}
    allowed = {}
    for row in allowed_contacts:
        key = frozenset((row['a'], row['b']))
        if len(key) != 2 or key in allowed or key not in candidates:
            raise ValueError('Invalid or unaudited declared contact: '+row['a']+' / '+row['b'])
        allowed[key] = row['reason']
    categories = {}
    interferences, contacts, undeclared = [], [], []
    for name, group in pairs.items():
        minimum, closest = math.inf, None
        declared_count = native_count = skipped = failures = 0
        # A lower bound may discharge a pair only against its own category's
        # observed minimum.  A zero elsewhere must never hide a positive margin.
        ordered = sorted(((bbox_distance(boxes[a], boxes[b]), a, b) for a, b in group),
                         key=lambda item: item[0])
        for lower, a, b in ordered:
            key = frozenset((a, b))
            declared = key in allowed
            if declared:
                declared_count += 1
            elif lower > CONTACT_DISTANCE_TOLERANCE_MM and lower >= minimum:
                skipped += 1
                continue
            distance = shapes[a].distToShape(shapes[b])[0]
            if not math.isfinite(distance) or distance < 0:
                raise ValueError('Invalid native separation: '+a+' / '+b)
            native_count += 1
            overlap = (shapes[a].common(shapes[b]).Volume
                       if distance <= CONTACT_DISTANCE_TOLERANCE_MM else 0.)
            if not math.isfinite(overlap) or overlap < 0:
                raise ValueError('Invalid native overlap: '+a+' / '+b)
            if declared:
                contacts.append({'a': a, 'b': b, 'category': name,
                                 'distance_mm': distance, 'overlap_mm3': overlap,
                                 'within_overlap_zero_tolerance': overlap <= OVERLAP_ZERO_TOLERANCE_MM3,
                                 'reason': allowed[key]})
                if overlap > OVERLAP_ZERO_TOLERANCE_MM3:
                    failures += 1
                    interferences.append({'a': a, 'b': b, 'category': name,
                                          'distance_mm': distance, 'volume_mm3': overlap,
                                          'reason': 'Declared contact has positive overlap'})
                continue
            if distance < minimum:
                minimum, closest = distance, {'a': a, 'b': b}
            if distance <= CONTACT_DISTANCE_TOLERANCE_MM:
                failures += 1
                undeclared.append({'a': a, 'b': b, 'category': name,
                                   'distance_mm': distance, 'overlap_mm3': overlap})
                interferences.append({'a': a, 'b': b, 'category': name,
                                      'distance_mm': distance, 'volume_mm3': overlap,
                                      'reason': 'Undeclared boundary contact or overlap'})
        categories[name] = {
            'passed': failures == 0,
            'checked_pairs': len(group), 'nonallowed_pairs': len(group)-declared_count,
            'declared_pairs': declared_count, 'exact_distance_checks': native_count,
            'broad_phase_skipped_pairs': skipped,
            'minimum_distance_mm': minimum if math.isfinite(minimum) else None,
            'closest_pair': closest,
        }
    observed = [(row['minimum_distance_mm'], row['closest_pair'])
                for row in categories.values() if row['minimum_distance_mm'] is not None]
    minimum, closest = min(observed, key=lambda item: item[0]) if observed else (None, None)
    return {
        'passed': not interferences,
        'checked_pairs': sum(row['checked_pairs'] for row in categories.values()),
        'exact_distance_checks': sum(row['exact_distance_checks'] for row in categories.values()),
        'minimum_nonallowed_distance_mm': minimum, 'closest_pair': closest,
        'categories': categories, 'interferences': interferences,
        'undeclared_contacts': undeclared, 'zero_distance_pairs': undeclared,
        'allowed_contacts': contacts, 'allowed_mount_contacts': contacts,
        'tolerances': {'contact_distance_mm': CONTACT_DISTANCE_TOLERANCE_MM,
                       'overlap_zero_mm3': OVERLAP_ZERO_TOLERANCE_MM3},
        'scope': 'Discrete added tooling/hose versus physical arm/cameras and cross-component tooling; '
                 'declared contacts excluded from minima; no full arm self-collision or hardware qualification',
    }


def aggregate_bodies(raw, ids):
    """Aggregate a split native vendor housing without relabeling its geometry."""
    rows = [raw[name] for name in ids]
    for name, row in zip(ids, rows):
        if row.get('error') is not None or 'volume_mm3' not in row:
            raise ValueError('Native measurement failed for '+name+': '+
                             str(row.get('error') or 'volume is unavailable'))
    volume = sum(row['volume_mm3'] for row in rows)
    if not rows or volume <= 0 or any(not row['closed'] for row in rows):
        raise ValueError('Native body is empty or open')
    return {'volume_mm3': volume,
            'world_center_of_mass_mm': [sum(row['center_of_mass'][i]*row['volume_mm3']
                for row in rows)/volume for i in range(3)],
            'bbox': {edge: [fn(row['bbox'][edge][i] for row in rows) for i in range(3)]
                     for edge, fn in [('min', min), ('max', max)]},
            'valid': True, 'solid_count': len(rows)}


def compare_geometry(solidcraft, freecad):
    if set(solidcraft) != set(freecad):
        raise ValueError('Native semantic body coverage differs')
    result = []
    for name, actual in solidcraft.items():
        expected = freecad[name]
        volume_error = abs(actual['volume_mm3']-expected['volume_mm3'])/expected['volume_mm3']
        center_error = math.dist(actual['world_center_of_mass_mm'], expected['world_center_of_mass_mm'])
        bounds_error = max(abs(a-b) for edge in ('min', 'max')
                           for a, b in zip(actual['bbox'][edge], expected['bbox'][edge]))
        result.append({'body': name, 'relative_volume_error': volume_error,
                       'center_error_mm': center_error, 'bbox_error_mm': bounds_error,
                       'passed': actual['valid'] and expected['valid']
                                 and volume_error < .001 and center_error < .01 and bounds_error < .01})
    return result


def frame_from_matrix(matrix):
    return {'origin': [matrix[i][3] for i in range(3)],
            'x': [matrix[i][0] for i in range(3)],
            'z': [matrix[i][2] for i in range(3)]}


def compare_derived_metrics(expected, actual, tolerance=1e-9):
    """Check independent arithmetic while preserving the leading report values."""
    mismatches = []
    maximum, count = 0., 0

    def visit(a, b, path):
        nonlocal maximum, count
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                mismatches.append(path+': keys differ')
            for key in a.keys() & b.keys():
                visit(a[key], b[key], path+'.'+key)
        elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) != len(b):
                mismatches.append(path+': lengths differ')
            for index, (x, y) in enumerate(zip(a, b)):
                visit(x, y, path+'['+str(index)+']')
        elif type(a) in (int, float) and type(b) in (int, float):
            count += 1
            if not math.isfinite(a) or not math.isfinite(b):
                mismatches.append(path+': nonfinite value')
                return
            error = abs(a-b)
            maximum = max(maximum, error)
            if error > tolerance:
                mismatches.append(path+': numeric values differ')
        elif type(a) is not type(b) or a != b:
            mismatches.append(path+': values differ')

    visit(expected, actual, 'metrics')
    return {'passed': not mismatches, 'maximum_absolute_numeric_difference': maximum,
            'absolute_numeric_tolerance': tolerance, 'numeric_values_compared': count,
            'mismatches': mismatches,
            'scope': 'Arithmetic agreement of independently evaluated source metrics; no physical tolerance claim'}


def compare_named_route(selected_route, state):
    """Compare complete route data while verifying optional joint provenance."""
    actual = state['hose_path']
    for route in (selected_route, actual):
        if 'joints_deg' in route and not compare_derived_metrics(
                state['joints_deg'], route['joints_deg'])['passed']:
            raise ValueError('Route joint provenance differs from its named arm state')
    expected = {key: value for key, value in selected_route.items() if key != 'joints_deg'}
    evaluated = {key: value for key, value in actual.items() if key != 'joints_deg'}
    return compare_derived_metrics(expected, evaluated, tolerance=1e-7)


def canonical_material_core(state, parameters):
    """Normalize only proven collinear subdivisions inside a physical part."""
    import pneumatic_hose as hose
    tolerance = 1e-9
    line_fields = {'kind', 'start_mm', 'end_mm', 'length_mm'}
    arc_fields = line_fields | {'through_mm', 'center_mm', 'axis', 'radius_mm', 'sweep_rad'}
    part_fields = {'id', 'kind', 'length_mm', 'segment_start_index', 'segment_count'}
    fit_fields = {'family', 'candidate_count', 'geometrically_feasible_candidate_count',
                  'geometric_rejections', 'clearance_rejections', 'selected_clearance',
                  'longer_geometric_candidates_not_checked', 'scope', 'tangent_distances_mm'}
    account_fields = set(MATERIAL_LENGTH_KEYS) | {'external_guide_straights_included_in_free_mm',
        'total_mm', 'sum_error_mm', 'service_loop_parameter_mm', 'parts', 'scope'}
    route_fields = {'format', 'controls_mm', 'segments', 'sample_points_mm', 'length_mm',
        'requested_bend_radius_mm', 'min_bend_radius_mm', 'qualified', 'carrier_path',
        'routing_frames', 'framed_crossings', 'crossing_control_indices', 'length_accounting'}
    state_fields = {'id', 'joints_deg', 'stroke_mm', 'motor_angle_deg', 'valve_angle_deg',
        'part_matrices', 'hose_path', 'hose_self_clearance', 'source_clearance', 'length_accounting',
        'carrier', 'hose_points_mm', 'hose_inner_radius_mm', 'hose_outer_radius_mm',
        'hose_slack_parameter_mm', 'theoretical_displacement_ul', 'actual_dispensed_volume_ul',
        'metrics', 'connection_interfaces', 'tip_seat', 'tip_tcp_mm'}
    path = state['hose_path']
    if (set(state) != state_fields or not route_fields <= set(path)
            or not set(path) <= route_fields | {'joints_deg'}):
        raise ValueError('Foreign or missing state/route comparison fields')
    if 'joints_deg' in path and not compare_derived_metrics(state['joints_deg'], path['joints_deg'])['passed']:
        raise ValueError('Route joint provenance differs from its arm state')
    route_material_checks(path, parameters)
    if not compare_derived_metrics(state['length_accounting'], path['length_accounting'])['passed']:
        raise ValueError('The state and route contain different material accounts')
    for name in ('hose_self_clearance', 'source_clearance'):
        if state[name].get('passed') is not True:
            raise ValueError('Raw source/self checks must pass before comparing a physical curve')

    def validate(segment):
        kind = segment.get('kind')
        if set(segment) != (line_fields if kind == 'line' else arc_fields if kind == 'arc' else set()):
            raise ValueError('Foreign or missing exact segment fields')
        start, end = [hose._point(segment[key]) for key in ('start_mm', 'end_mm')]
        length = segment['length_mm']
        if type(length) not in (int, float) or not math.isfinite(length) or length <= 0:
            raise ValueError('A physical curve needs a positive finite length')
        if kind == 'line':
            if abs(math.dist(start, end)-length) > tolerance:
                raise ValueError('Line geometry and physical length differ')
            return
        center, axis = [hose._point(segment[key]) for key in ('center_mm', 'axis')]
        radius, angle = segment['radius_mm'], segment['sweep_rad']
        if (any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                for value in (radius, angle)) or angle >= 2*math.pi):
            raise ValueError('An exact arc needs a positive finite radius and sub-turn sweep')
        radial = hose._sub(start, center)
        if (abs(hose._dot(axis, axis)-1) > tolerance or abs(hose._dot(axis, radial)) > tolerance
                or abs(math.dist(start, center)-radius) > tolerance
                or abs(radius*angle-length) > tolerance):
            raise ValueError('Arc frame or physical length differs from its geometry')
        for key, fraction in [('through_mm', .5), ('end_mm', 1.)]:
            if math.dist(hose._point(segment[key]), hose._add(center,
                    hose._rotate(radial, axis, angle*fraction))) > tolerance:
                raise ValueError('The exact arc trace was changed')

    def tangent(segment, end=False):
        if segment['kind'] == 'line':return hose._unit(hose._sub(segment['end_mm'], segment['start_mm']))
        return hose._unit(hose._cross(segment['axis'],
            hose._sub(segment['end_mm' if end else 'start_mm'], segment['center_mm'])))

    def curves(segments):
        hose._joined_path({'segments': segments})
        result, traces = [], []
        for raw in segments:
            validate(raw);segment = copy.deepcopy(raw)
            if result and result[-1]['kind'] == segment['kind'] == 'line':
                before = result[-1]
                trace = traces[-1]+[segment['start_mm'], segment['end_mm']]
                direction = hose._unit(hose._sub(segment['end_mm'], before['start_mm']))
                collinear = all(math.sqrt(hose._dot(offset, offset)) <= tolerance for offset in
                    (hose._cross(hose._sub(point, before['start_mm']), direction) for point in trace))
                if (math.dist(before['end_mm'], segment['start_mm']) <= tolerance and collinear
                        and math.dist(tangent(before, True), tangent(segment)) <= tolerance):
                    merged = {**before, 'end_mm': segment['end_mm'],
                              'length_mm': before['length_mm']+segment['length_mm']}
                    validate(merged);result[-1] = merged;traces[-1] = trace
                    continue
            result.append(segment);traces.append([segment['start_mm'], segment['end_mm']])
        return result

    account = path['length_accounting']
    if set(account) != account_fields:
        raise ValueError('Foreign or missing material-account fields')
    physical = {key: copy.deepcopy(value) for key, value in account.items() if key != 'parts'}
    parts, cursor = [], 0
    for part in account['parts']:
        if not part_fields <= set(part) or not set(part) <= part_fields | {'bare_fit'}:
            raise ValueError('Foreign or missing physical-part fields')
        if 'bare_fit' in part:
            if not isinstance(part['bare_fit'], dict) or not set(part['bare_fit']) <= fit_fields:
                raise ValueError('Foreign bare-span derivation fields')
            json.dumps(part['bare_fit'], allow_nan=False)
        if part['segment_start_index'] != cursor:
            raise ValueError('Physical parts must remain an ordered contiguous partition')
        count = part['segment_count'];geometry = curves(path['segments'][cursor:cursor+count]);cursor += count
        parts.append({'id': part['id'], 'kind': part['kind'], 'length_mm': part['length_mm'],
            'curves': geometry, 'start_mm': geometry[0]['start_mm'], 'end_mm': geometry[-1]['end_mm'],
            'start_tangent': tangent(geometry[0]), 'end_tangent': tangent(geometry[-1], True)})
    if cursor != len(path['segments']):
        raise ValueError('Physical material does not cover the complete curve')
    physical['parts'] = parts
    keys = ('id', 'joints_deg', 'stroke_mm', 'motor_angle_deg', 'valve_angle_deg',
            'part_matrices', 'tip_tcp_mm', 'connection_interfaces', 'tip_seat',
            'hose_inner_radius_mm', 'hose_outer_radius_mm', 'hose_slack_parameter_mm',
            'theoretical_displacement_ul', 'actual_dispensed_volume_ul', 'metrics')
    protected = curves(path['carrier_path']['segments'])
    delivered = curves(state['carrier']['path']['segments'])
    if not compare_derived_metrics(protected, delivered)['passed']:
        raise ValueError('The delivered carrier differs from its protected material curve')
    return {**{key: state[key] for key in keys}, 'length_accounting': physical,
            'route_frames': {key: path[key] for key in ('controls_mm', 'routing_frames',
                'framed_crossings', 'crossing_control_indices', 'requested_bend_radius_mm',
                'min_bend_radius_mm', 'qualified', 'length_mm')},
            'carrier_segments': protected,
            'carrier': {key: value for key, value in state['carrier'].items() if key != 'path'}}


def route_derivation_diagnostics(path):
    """Retain subdivision/fitter data separately from proven curve equality."""
    return [{key: copy.deepcopy(value) for key, value in part.items()
             if key in ('id', 'segment_start_index', 'segment_count', 'bare_fit')}
            for part in path['length_accounting']['parts']]


def assembly_commands(model, spec, p, state_name, *, loop_parameter_mm=None):
    """Preserve native arm joints and rigidly attach source-derived new parts."""
    import tube_carrier_model as portable
    import pneumatic_hose
    import spatial_hose_carrier
    arm = model.arm(spec)
    own = model.expanded(spec, p)
    state = (model.state(spec, p, state_name) if loop_parameter_mm is None else
             model.state(spec, p, state_name, loop_parameter_mm=loop_parameter_mm))
    native_spec = model.cad_spec(spec, p)
    zero = {joint['id']: 0 for joint in own['joints']}

    class Provider:
        SOURCE = model.SOURCE
        expanded = staticmethod(lambda _spec, _p: own)
        pose = staticmethod(lambda _spec, _p: zero)
        samples = staticmethod(lambda _spec, _p: [])

    commands = [{'command': 'joint.drive', 'params': {'joint': joint['id'], 'value': 0, 'quiet': True}}
                for joint in arm['joints']]
    commands.append({'command': 'joint.solve', 'params': {}})
    additions = portable.solidcraft_commands(native_spec, p, Provider)
    existing_parameters = set(arm['parameters'])
    if existing_parameters & set(native_spec['parameters']):
        raise ValueError('New syringe parameters shadow existing arm parameters')
    for command in additions:
        if command['command'] in {'joint.drive', 'joint.solve'}:
            continue
        if command['command'] == 'component.create':
            # A grounded nested occurrence does NOT follow a moving host in SC.
            command['params']['grounded'] = False
        commands.append(command)
    for group, mount in model.mounts(spec, p).items():
        commands.append({'command': 'joint.create', 'params': {
            'name': group+'_ArmAttachment', 'type': 'rigid',
            'a': {'occurrence': mount['link'], 'frame': frame_from_matrix(mount['zero_transform'])},
            'b': {'occurrence': group, 'frame': frame_from_matrix(robot.identity())},
            'values': [], 'flip': True, 'quiet': True}})
    commands.append({'command': 'joint.motion_link', 'params': {
        'a': 'PumpStroke', 'b': 'MotorRotation', 'ratio': 360/p['pitch'], 'offset': 0}})
    commands += [{'command': 'joint.drive', 'params': {'joint': joint['id'], 'value': value, 'quiet': True}}
                 for joint, value in zip(arm['joints'], state['joints_deg'])]
    commands += [{'command': 'joint.drive', 'params': {'joint': name, 'value': value, 'quiet': True}}
                 for name, value in model.pose(spec, p, state_name).items() if name != 'MotorRotation']
    commands.append({'command': 'joint.solve', 'params': {}})
    commands += pneumatic_hose.solidcraft_commands(state['hose_path'], state['hose_inner_radius_mm'],
                                                  state['hose_outer_radius_mm'])
    dynamic = carrier_bodies(state)
    if dynamic:
        commands += spatial_hose_carrier.solidcraft_envelope_commands(state['carrier'])
        commands += spatial_hose_carrier.solidcraft_links_commands(state['carrier'])
        commands += [
            {'command': 'component.create', 'params': {'name': 'CarrierSnapshot', 'parent': 'root',
                                                      'activate': False, 'grounded': True}},
            {'command': 'component.move_bodies', 'params': {'component': 'CarrierSnapshot',
                'bodies': ['CarrierEnvelope', *state['carrier']['native_aliases']]}},
            {'command': 'appearance.assign', 'params': {'bodies': ['CarrierEnvelope'],
                                                       'color': '#668d71', 'opacity': .15}},
        ]
    cones = [row['id'] for row in arm_bodies(arm) if row['role'] == 'viewing_cone']
    commands += [{'command': 'browser.visibility', 'params': {'items': cones, 'visible': False}},
                 {'command': 'browser.visibility', 'params': {'folder': 'joints', 'visible': False}},
                 {'command': 'document.metadata.set', 'params': {'values': {
                     'org.solidcraftbot.arm-syringe': {'source': str(model.SOURCE.relative_to(model.ROOT)),
                         'source_sha256': digest(model.SOURCE), 'state': state_name,
                         'qualification': spec['qualification'],
                         'operating_window_status': spec['operating_window_status'],
                         'operating_window_deg': spec['operating_window_deg'],
                         'connection_interfaces': state['connection_interfaces'],
                         'tip_seat': state['tip_seat'],
                         'hose': 'Static shape for this named arm pose; no automatic deformation after manual arm editing',
                         'carrier': {'source': spec.get('hose_carrier'), 'delivered_bodies': [row['id'] for row in dynamic],
                             'nominal_link_count': state['carrier']['nominal_link_count'] if dynamic else 0,
                             'scope': 'Static collar/shell representations; filled outer guard checked separately. '
                                      'No exact vendor channels, native articulated chain, or automatic deformation.'}}}}}]
    return commands


def semantic_measurements(measurement, arm_rows, own, aliases, state=None):
    actual = {row['name']: row for row in measurement['bodies']}
    rows = {row['id']: aggregate_bodies(actual, aliases.get(row['id'], [row['id']])) for row in arm_rows}
    extras = carrier_bodies(state) if state is not None else []
    extra_aliases = carrier_aliases(state) if state is not None else {}
    rows.update({row['id']: aggregate_bodies(actual, extra_aliases.get(row['id'], [row['id']]))
                 for row in own['bodies']+extras})
    rows['PneumaticHose'] = aggregate_bodies(actual, ['PneumaticHose'])
    expected = {name for row in arm_rows for name in aliases.get(row['id'], [row['id']])}
    expected.update(row['id'] for row in own['bodies'])
    expected.update(name for row in extras for name in extra_aliases.get(row['id'], [row['id']]))
    expected.add('PneumaticHose')
    if expected != set(actual):
        raise ValueError('Unexpected or incomplete native arm/tool body coverage')
    return rows


def source_files(model, spec):
    paths = [model.SOURCE, Path(model.__file__), Path(__file__),
             model.ROOT/'scripts/build_arm_syringe_freecad.py',
             model.ROOT/'scripts/pneumatic_hose.py',
             model.ROOT/'scripts/syringe_pipette.py',
             model.ROOT/'model/syringe-pipette.shared.json',
             model.ROOT/'model/syringe-pipette.schema.json',
             model.ROOT/'scripts/tube_carrier_model.py',
             model.ROOT/'scripts/build_tube_carrier_freecad.py',
             model.ROOT/'scripts/build_instrument_concepts.py',
             model.ROOT/'scripts/instrument_concept.py',
             model.ROOT/'scripts/tube_cam_model.py', model.ROOT/'scripts/tube_frame_model.py',
             model.ROOT/'scripts/robot_spec.py', model.ROOT/'scripts/robot_components.py',
             model.ROOT/'scripts/robot_cameras.py', model.ROOT/'scripts/assembly_model.py',
             model.ROOT/'scripts/tool_paths.py', model.ROOT/'scripts/build_neutral_freecad.py',
             model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',
             model.ROOT/'scripts/freecad/persist_station_view.py',
             model.ROOT/'scripts/freecad/persist_view.py',
             model.ROOT/'model/arm-syringe.schema.json',
             model.ROOT/'model/robot.json']
    if hasattr(model, 'source_dependencies'):
        paths += model.source_dependencies(spec)
    return sorted(set(map(Path, paths)))


def validate_window_scan(scan, model, spec, parameters):
    """Bind named solved material lengths; Cartesian endpoint trials are diagnostic."""
    if (scan.get('format') != 'solidcraftbot.arm-syringe-window-scan/1'
            or scan.get('sample_coverage', {}).get('complete') is not True or scan.get('errors') != []
            or scan.get('source_files_unchanged_during_scan') is not True
            or scan.get('source_file_unchanged_during_scan') is not True):
        raise ValueError('A complete source-stable classified diagnostic scan is required')
    if (Path(scan['source_file']).resolve() != model.SOURCE.resolve()
            or scan['source_file_sha256'] != digest(model.SOURCE)):
        raise ValueError('Window scan is bound to another construction source')
    canonical = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode()).hexdigest()
    pins = scan['source_pins']
    if pins.get('evaluated_source_canonical_sha256') != canonical:
        raise ValueError('Window scan evaluated a different source definition')
    if not pins.get('files_sha256'):
        raise ValueError('Window scan lacks producer/source pins')
    for name, checksum in pins['files_sha256'].items():
        path = (model.ROOT/name).resolve()
        if not path.is_relative_to(model.ROOT.resolve()) or digest(path) != checksum:
            raise ValueError('Window-scan dependency differs: '+name)
    if scan.get('parameters') != parameters:
        raise ValueError('Window scan evaluated different construction parameters')
    if (scan['sample_coverage'].get('named_state_count') != len(spec['states'])
            or scan['sample_coverage'].get('named_states_outside_window')):
        raise ValueError('Window scan does not cover the current named states')
    coverage = scan['sample_coverage']
    if coverage.get('named_state_support_complete') is not True:
        raise ValueError('Every named state must have a solved supported route')
    unsupported = scan.get('diagnostic_unsupported')
    if (not isinstance(unsupported, list) or any(not isinstance(row, dict)
            or not isinstance(row.get('classification'), str) or not row['classification'] for row in unsupported)):
        raise ValueError('Unsupported Cartesian endpoint trials must remain explicitly classified')
    validate_named_band(scan.get('named_state_band', {}), spec, parameters)
    if abs(scan['suggested_hose_length_mm']-parameters['hoseLength']) > 1e-7:
        raise ValueError('The suggested cut must come from the demonstrated named-state band')
    qualification = scan.get('qualification')
    if not isinstance(qualification, dict) or not qualification or any(value is not False for value in qualification.values()):
        raise ValueError('Finite length sampling cannot claim physical or continuous qualification')


def bind_window_scan(model, spec, parameters, overrides, out):
    """Bind a validated scan snapshot; re-evaluate changed parameter variants."""
    source = model.ROOT/'exports/arm-syringe/window-scan.json'
    destination = out/'window-scan.json'
    if overrides:
        import arm_syringe_window
        before = digest(model.SOURCE)
        scan = arm_syringe_window.scan(spec, parameters)
        scan.update(source_file=str(model.SOURCE.resolve()), source_file_sha256=before,
                    source_file_unchanged_during_scan=digest(model.SOURCE) == before)
        validate_window_scan(scan, model, spec, parameters)
        destination.write_text(json.dumps(scan, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        origin = None
    else:
        raw = source.read_bytes()
        scan = json.loads(raw)
        validate_window_scan(scan, model, spec, parameters)
        destination.write_bytes(raw)
        origin = {'path': str(source.relative_to(model.ROOT)), 'sha256': hashlib.sha256(raw).hexdigest()}
    band = scan['named_state_band']
    return {'path': str(destination.relative_to(model.ROOT)), 'sha256': digest(destination),
            'source_report': origin, 'regenerated_for_parameter_overrides': bool(overrides),
            'sample_coverage': scan['sample_coverage'],
            'common_endpoint_bracket': scan.get('common_endpoint_bracket'),
            'named_state_band': {key: band[key] for key in
                ('format', 'status', 'scope', 'common_band', 'cut_selection', 'qualification')},
            'named_state_support_complete': scan['sample_coverage']['named_state_support_complete'],
            'diagnostic_unsupported_count': len(scan['diagnostic_unsupported']),
            'extrema': scan['extrema'], 'scope': scan['scope'], 'qualification': scan['qualification']}


def presentation_source(arm, own):
    looks = robot.appearances(arm)['appearances']
    bodies = []
    for row in arm_bodies(arm):
        look = looks['bodies'].get(row['id']) or looks['components'][row['group']]
        color = look.get('color', [180, 190, 200])
        bodies.append({'id': row['id'], 'appearance': {
            'color': '#'+''.join('%02x'%int(v) for v in color),
            'opacity': 0 if row['role'] == 'viewing_cone' else look.get('opacity', 1)}})
    bodies += own['bodies']
    bodies.append({'id': 'PneumaticHose', 'appearance': {'color': '#66b8d4', 'opacity': .85}})
    return {'bodies': bodies}


def persist_assembly(path, source, geometry, cone_ids):
    """Use existing presentation writer; hide illustrative cones without geometry edits."""
    import xml.etree.ElementTree as ET
    import zipfile
    from persist_station_view import persist
    physical = [row for row in geometry if row['body'] not in cone_ids]
    proof = persist(path, source, physical)
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(entries['Document.xml'])
    hidden = set()
    for obj in document.findall('ObjectData/Object'):
        body = obj.find("Properties/Property[@name='SourceBody']/String")
        if body is not None and body.get('value') in cone_ids:
            hidden.add(obj.get('name'))
    gui = ET.fromstring(entries['GuiDocument.xml'])
    for obj in gui.findall('ViewProviderData/ViewProvider'):
        if obj.get('name') in hidden:
            flag = obj.find("Properties/Property[@name='Visibility']/Bool")
            if flag is None:
                raise ValueError('Saved cone view provider lacks visibility')
            flag.set('value', 'false')
    entries['GuiDocument.xml'] = ET.tostring(gui, encoding='utf-8', xml_declaration=True)
    temp = path.with_suffix('.presentation-new')
    with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(temp) as archive:
        if archive.read('Document.xml') != entries['Document.xml']:
            raise ValueError('Presentation altered native geometry')
    temp.replace(path)
    return {**proof, 'hidden_camera_cones': len(hidden), 'camera_fit_uses_physical_bodies': True}


def build(args):
    import arm_syringe as model
    started = time.monotonic()
    spec = model.load()
    overrides = {}
    for item in args.parameter:
        key, separator, value = item.partition('=')
        if not separator or key in overrides:
            raise ValueError('Use unique --parameter NAME=VALUE entries')
        overrides[key] = float(value)
    p = model.parameters(spec, overrides)
    states = args.state or list(spec['states'])
    if not states or len(states) != len(set(states)) or set(states)-set(spec['states']):
        raise ValueError('Select distinct named arm states from the source')
    arm = model.arm(spec)
    own = model.expanded(spec, p)
    arm_rows = arm_bodies(arm)
    cones = {row['id'] for row in arm_rows if row['role'] == 'viewing_cone'}
    if {row['id'] for row in own['bodies']} & {row['id'] for row in arm_rows}:
        raise ValueError('New part names shadow the actual arm')
    backends = ['freecad', 'solidcraft'] if args.backend == 'both' else [args.backend]
    arm_report = args.arm_report if args.arm_report.is_absolute() else model.ROOT/args.arm_report
    caches = {name: checked_arm_cache(arm_report, name, model.ROOT) for name in backends}
    pins = {str(path.relative_to(model.ROOT)): digest(path) for path in source_files(model, spec)}
    stem = 'arm-syringe-'+digest(model.SOURCE)[:12]
    revision, number = stem, 1
    while (model.ROOT/'cad/generated'/revision).exists():
        number += 1;revision = stem+'-r'+str(number)
    cad, out, renders = [model.ROOT/folder/revision for folder in ('cad/generated', 'exports/generated', 'renders')]
    for directory in (cad, out, renders):directory.mkdir(parents=True)
    window_scan = bind_window_scan(model, spec, p, overrides, out)
    bound_scan = json.loads((model.ROOT/window_scan['path']).read_text(encoding='utf-8'))
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    results = []
    for name in states:
        print('Arm syringe: '+name, flush=True)
        selected = bound_scan['named_state_band']['selected_states'][name]
        state = model.state(spec, p, name, loop_parameter_mm=selected['loop_parameter_mm'])
        require_hose_self_clearance(state)
        material = route_material_checks(state['hose_path'], p)
        selected_agreement = compare_named_route(selected['route'], state)
        if not selected_agreement['passed']:
            raise ValueError('The generated route differs from its solved named length witness: '+name)
        dynamic = carrier_bodies(state)
        if spec.get('hose_carrier') is not None and not dynamic:
            raise ValueError('The selected carrier source produced no native carrier representations')
        if {row['id'] for row in dynamic} & ({row['id'] for row in arm_rows+own['bodies']} | {'PneumaticHose'}):
            raise ValueError('Carrier semantic body names shadow existing geometry')
        case = {'state': name, 'overrides': overrides, 'arm_report': str(arm_report),
                'metrics': state['metrics'], 'compiled_state': state,
                'named_length_witness': {key: value for key, value in selected.items() if key != 'route'}}
        case_path = out/(name+'.case.json');write(case_path, case)
        files = {'case': case_path}
        def solidcraft_backend():
            commands_path = out/(name+'.commands.json')
            write(commands_path, {'source_sha256': digest(model.SOURCE),
                                 'commands': assembly_commands(model, spec, p, name,
                                    loop_parameter_mm=selected['loop_parameter_mm'])})
            sc_path, measured = cad/(name+'.sc'), out/(name+'.solidcraft.json')
            subprocess.run([args.solidcraft_cli, 'run', str(commands_path), '--in', caches['solidcraft']['path'],
                '--save', str(sc_path), '--json-out', str(measured), '--quiet'], check=True, cwd=model.ROOT)
            sc_raw = json.loads(measured.read_text(encoding='utf-8'))
            rows = semantic_measurements(sc_raw, arm_rows, own, caches['solidcraft']['aliases'], state)
            return {'rows': rows, 'files': {'solidcraft': sc_path, 'solidcraft_measurements': measured,
                                           'commands': commands_path}}

        def freecad_backend():
            fc_path, checked = cad/(name+'.FCStd'), out/(name+'.freecad.json')
            subprocess.run([args.freecad_python, str(model.ROOT/'scripts/build_arm_syringe_freecad.py'),
                str(case_path), str(fc_path), str(checked)], check=True, cwd=model.ROOT,
                env=freecad_environment(args.freecad_python))
            report = json.loads(checked.read_text(encoding='utf-8'))
            rows = report['geometry']
            presentation = persist_assembly(fc_path, presentation_source(arm, {**own, 'bodies': own['bodies']+dynamic}),
                [{'body': key, **value} for key, value in rows.items()], cones)
            return {'rows': rows, 'report': report, 'presentation': presentation,
                    'files': {'freecad': fc_path, 'freecad_validation': checked,
                              'freecad_parts': Path(report['own_parts_file'])}}

        workers = {'solidcraft': solidcraft_backend, 'freecad': freecad_backend}
        # Independent native backends share only read-only case/source data.
        # Join both before comparing geometry or starting the next state.
        with ThreadPoolExecutor(max_workers=len(backends)) as pool:
            pending = {backend: pool.submit(workers[backend]) for backend in backends}
            completed = {backend: pending[backend].result() for backend in backends}
        for value in completed.values():files.update(value['files'])
        sc_result, fc_result = completed.get('solidcraft'), completed.get('freecad')
        sc_rows = sc_result['rows'] if sc_result else None
        fc_rows = fc_result['rows'] if fc_result else None
        fc_report = fc_result['report'] if fc_result else None
        presentation = fc_result['presentation'] if fc_result else None
        cross = compare_geometry(sc_rows, fc_rows) if sc_rows is not None and fc_rows is not None else None
        passed = (fc_report is None or fc_report['passed']) and (cross is None or all(row['passed'] for row in cross))
        if sc_rows is not None:passed = passed and all(row['valid'] and row['volume_mm3'] > 0 for row in sc_rows.values())
        item = {'id': name, 'passed': passed, 'state': state, 'metrics': state['metrics'],
                'semantic_body_count': len(arm_rows)+len(own['bodies'])+len(dynamic)+1,
                'carrier_bodies': dynamic, 'carrier_aliases': carrier_aliases(state),
                'carrier_checks': fc_report.get('carrier_checks') if fc_report else None,
                'pneumatic_connections': fc_report.get('pneumatic_connections') if fc_report else None,
                'tip_seat_checks': fc_report.get('tip_seat_checks') if fc_report else None,
                'air_path_checks': fc_report.get('air_path_checks') if fc_report else None,
                'route_material_checks': material, 'named_length_witness': case['named_length_witness'],
                'named_route_agreement': selected_agreement,
                'body_comparisons': cross, 'freecad_presentation': presentation,
                'clearance_checks': fc_report['clearance_checks'] if fc_report else None,
                'files': {key: str(path.relative_to(model.ROOT)) for key, path in files.items()},
                'artifact_sha256': {key: digest(path) for key, path in files.items()}}
        results.append(item);write(out/'cases-progress.json', results)
        if not passed:
            raise AssertionError('Arm-mounted syringe case failed: '+name)
    views = {}
    if 'solidcraft' in backends and not args.no_render:
        name = spec['default_state'] if spec['default_state'] in states else states[0]
        row = next(row for row in results if row['id'] == name)
        sc_path = model.ROOT/row['files']['solidcraft']
        measured = json.loads((model.ROOT/row['files']['solidcraft_measurements']).read_text())
        geometry = semantic_measurements(measured, arm_rows, own, caches['solidcraft']['aliases'], row['state'])
        physical = [value['bbox'] for key, value in geometry.items() if key not in cones]
        lo = [min(box['min'][i] for box in physical) for i in range(3)]
        hi = [max(box['max'][i] for box in physical) for i in range(3)]
        cameras = {'overview': {'target': [(a+b)/2 for a, b in zip(lo, hi)], 'yaw': 2.79,
                                'pitch': .70, 'distance': math.dist(lo, hi)*1.8, 'fov': 0}}
        cameras['overview_close'] = {**cameras['overview'], 'distance': cameras['overview']['distance']*.68}
        for label, group in [('pump', 'PumpFrame'), ('tip', 'WristHead')]:
            chosen = [geometry[body['id']]['bbox'] for body in own['bodies'] if body['component'] == group]
            a = [min(box['min'][i] for box in chosen) for i in range(3)]
            b = [max(box['max'][i] for box in chosen) for i in range(3)]
            cameras[label] = {'target': [(x+y)/2 for x, y in zip(a, b)],
                              'yaw': 2.79 if label == 'pump' else -.8,
                              'pitch': .70 if label == 'pump' else .4,
                              'distance': max(120, math.dist(a, b)*1.8), 'fov': 0}
        plans = {view: {'camera': camera, 'row': row} for view, camera in cameras.items()}
        for label, interface_name in [('syringe_junction', 'pump'), ('pipette_junction', 'tip')]:
            interface = row['state']['connection_interfaces'][interface_name]
            points = [interface[key] for key in ('material_end_mm', 'socket_mouth_mm', 'unsupported_exit_mm')]
            if interface_name == 'tip':points.append(row['state']['tip_tcp_mm'])
            a = [min(point[i] for point in points) for i in range(3)]
            b = [max(point[i] for point in points) for i in range(3)]
            plans[label] = {'row': row, 'camera': {
                'target': [(x+y)/2 for x, y in zip(a, b)],
                'yaw': 2.79 if interface_name == 'pump' else -.8,
                'pitch': .70 if interface_name == 'pump' else .4,
                'distance': max(85, math.dist(a, b)*2.5), 'fov': 0},
                'interface': interface_name}
        arcs = [(segment['radius_mm'], result, index, segment)
                for result in results for index, segment in enumerate(result['state']['hose_path']['segments'])
                if segment['kind'] == 'arc']
        if arcs:
            radius, bend_row, index, segment = min(arcs, key=lambda value: value[0])
            plans['tightest_bend'] = {'row': bend_row,
                'camera': {'target': segment['through_mm'], 'yaw': 2.79, 'pitch': .70,
                           'distance': max(120, min(300, radius*5)), 'fov': 0},
                'geometry_witness': {'segment_index': index, 'achieved_radius_mm': radius}}
        guide = row['state']['hose_path']['carrier_path']
        endpoints = [guide['segments'][0]['start_mm'], guide['segments'][-1]['end_mm']]
        guide_part = next(part for part in row['state']['length_accounting']['parts']
                          if part['kind'] == 'nominal_carrier')
        guide_indices = range(guide_part['segment_start_index'],
                              guide_part['segment_start_index']+guide_part['segment_count'])
        nearby = [(math.dist(segment['through_mm'], endpoint), index, segment, endpoint)
                  for index, segment in enumerate(row['state']['hose_path']['segments'])
                  if segment['kind'] == 'arc' and index not in guide_indices for endpoint in endpoints]
        if nearby:
            _, index, segment, endpoint = min(nearby, key=lambda value: value[0])
            plans['guide_transition'] = {'row': row,
                'camera': {'target': [(a+b)/2 for a, b in zip(segment['through_mm'], endpoint)],
                           'yaw': 2.79, 'pitch': .70,
                           'distance': max(160, math.dist(segment['through_mm'], endpoint)*3), 'fov': 0},
                'geometry_witness': {'segment_index': index, 'achieved_radius_mm': segment['radius_mm'],
                                     'guide_endpoint_mm': endpoint}}
        upright = next((result for result in results if result['id'] == 'upright'), None)
        if upright is not None:
            for label, interface_name in [('pump_section', 'pump'), ('tip_section', 'tip')]:
                interface = upright['state']['connection_interfaces'][interface_name]
                points = [interface['material_end_mm'], interface['unsupported_exit_mm']]
                if interface_name == 'tip':points.append(upright['state']['tip_tcp_mm'])
                a = [min(point[i] for point in points) for i in range(3)]
                b = [max(point[i] for point in points) for i in range(3)]
                plans[label] = {'row': upright, 'section': {'plane': 'XZ', 'at': 0, 'flip': True, 'hatch': True},
                    'camera': {'target': [(x+y)/2 for x, y in zip(a, b)], 'yaw': 0, 'pitch': 0,
                               'distance': max(95, math.dist(a, b)*2.5), 'fov': 0},
                    'scope': 'Upright native XZ/y=0 section through the syringe or pipette axes; visual fit inspection only'}
        for view, plan in plans.items():
            camera = plan['camera'];view_row = plan['row']
            view_path = model.ROOT/view_row['files']['solidcraft']
            image = renders/(view.replace('_', '-')+'.png')
            command = [args.solidcraft_cli, 'snapshot']
            presentation = {}
            if 'section' in plan:
                script = out/(view+'.render.commands.json')
                write(script, {'commands': [
                    {'command': 'inspect.section', 'params': {'clear': True}},
                    {'command': 'inspect.section', 'params': plan['section']}]})
                command.append(str(script))
                presentation = {'section': plan['section'], 'command_file': str(script.relative_to(model.ROOT)),
                                'command_sha256': digest(script)}
            subprocess.run(command+['--in', str(view_path), '--out', str(image),
                '--width', '1400', '--height', '1100', '--camera', json.dumps(camera),
                '--quality', 'fine', '--no-grid', '--no-axes'], check=True, cwd=model.ROOT)
            if digest(view_path) != view_row['artifact_sha256']['solidcraft']:
                raise ValueError('Rendering altered the checked native SolidCraft input')
            views[view] = {'path': str(image.relative_to(model.ROOT)), 'sha256': digest(image), 'camera': camera,
                           'state': view_row['id'], 'native_artifact': view_row['files']['solidcraft'],
                           'native_artifact_sha256': view_row['artifact_sha256']['solidcraft'],
                           **{key: value for key, value in plan.items() if key not in ('row', 'camera', 'section')},
                           **presentation}
    if any(digest(model.ROOT/name) != checksum for name, checksum in pins.items()):
        raise ValueError('A source changed while building; proof is not current')
    for cache in caches.values():
        if digest(cache['path']) != cache['sha256']:
            raise ValueError('The original arm artifact changed during composition')
    if digest(model.ROOT/window_scan['path']) != window_scan['sha256']:
        raise ValueError('Bound window scan changed during the native build')
    report = {'format': 'solidcraftbot.arm-syringe-build/1', 'passed': all(row['passed'] for row in results),
              'revision': revision, 'source': str(model.SOURCE.relative_to(model.ROOT)),
              'source_sha256': digest(model.SOURCE), 'source_files_sha256': pins,
              'backends': args.backend, 'arm_cache': caches,
              'window_scan': window_scan,
              'states': results, 'renders': views, 'qualification': spec['qualification'],
              'scope': 'Source-bound dedicated 1 mL arm and named static hose configurations; no hardware execution',
              'limitations': spec['limitations']+[
                  'Construction dimension changes require regeneration; native stroke and motor rotation remain coupled.',
                  'The saved hose and carrier are static for their named pose and must be regenerated after manual arm-joint changes.',
                  'FreeCAD presentation metadata is saved; no FreeCAD GUI rendering qualification is claimed.'],
              'elapsed_s': time.monotonic()-started}
    write(out/'build-report.json', report)
    latest = model.ROOT/'cad/arm-syringe';latest.mkdir(parents=True, exist_ok=True)
    write(latest/'shared-build-report.json', report)
    print('Arm-mounted syringe passed: '+str(out/'build-report.json'), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['both', 'freecad', 'solidcraft'], default='both')
    parser.add_argument('--arm-report', type=Path, default=Path('exports/generated/build-report.json'))
    parser.add_argument('--state', action='append')
    parser.add_argument('--parameter', action='append', default=[], metavar='NAME=VALUE')
    parser.add_argument('--no-render', action='store_true')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args = parser.parse_args()
    needed = {'freecad_python', 'solidcraft_cli'} if args.backend == 'both' else {
        'freecad_python' if args.backend == 'freecad' else 'solidcraft_cli'}
    tool_paths.resolve_tool_arguments(parser, args, required=needed)
    return build(args)


if __name__ == '__main__':
    main()
