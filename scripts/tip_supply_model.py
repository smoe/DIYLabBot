"""Evidence-bound tip dimensions and occupancy; no invented physical geometry."""
import copy
import json
import math
from pathlib import Path
import re

import assembly_model as assembly
import lab_layout_model as layout
import robot_spec as robot
import tip_collector_model as collector

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/tip-supply.shared.json'
INSTANCES = ROOT / 'model/tip-supply.instances.json'
SCHEMA = ROOT / 'model/tip-supply.schema.json'
VARIANTS = {'tip_10_ul': 10, 'tip_200_ul': 200, 'tip_1000_ul': 1000}
MEASUREMENTS = {
    'shaft_diameter_max': 'mm', 'collar_diameter_min': 'mm',
    'wall_thickness': 'mm', 'tip_mass': 'g', 'nipple_outer_diameter': 'mm',
    'nipple_insertion_length': 'mm', 'access_gap_above_collar': 'mm',
    'vertical_running_clearance': 'mm', 'withdrawal_force': 'N',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def exact(value, keys, name):
    require(isinstance(value, dict) and set(value) == set(keys.split()), 'Explicit '+name+' fields required')


def parameters(spec, variant):
    require(variant in spec['variants'], 'Unknown tip variant')
    derived = assembly.parameter_variant(spec, spec['variants'][variant]['overrides'])
    return robot.parameters(derived)


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    validate(spec)
    return spec


def validate(spec):
    exact(spec, 'format id revision date status units coordinates sources parameters variants geometry fit_to open_tasks limitations', 'tip source')
    require(spec['format'] == 'solidcraftbot.tip-supply/1' and spec['id'] == 'TipSupply', 'Tip-supply format required')
    require(spec['status'] == 'Concept; no manufacturing release', 'Concept status required')
    require(spec['units'] == {'length': 'mm', 'angle': 'deg', 'volume': 'uL', 'mass': 'g', 'force': 'N'}, 'Explicit tip units required')
    require(set(spec['variants']) == set(VARIANTS), 'The 10, 200 and 1000 uL variants are required')
    for source in spec['sources'].values():
        exact(source, 'title url retrieved_on file sha256 scope', 'manufacturer source')
        require(all(isinstance(v, str) and v for v in source.values()), 'Nonempty manufacturer provenance required')
        require(source['url'].startswith('https://') and re.fullmatch('[A-Za-z0-9_.-]+', source['file'])
                and re.fullmatch('[a-f0-9]{64}', source['sha256']), 'Source URL, basename and SHA-256 required')
    def evidence(item):
        require(item['source_id'] in spec['sources'] and isinstance(item['locator'], str) and item['locator'], 'Known source and precise locator required')
    expected_units = {k: 'mm' for k in ('tip_length', 'collar_od', 'inlet_id', 'body_diameter_callout', 'outlet_od', 'outlet_id', 'pitch', 'strip_axis_span', 'tray_axis_span_x')}
    expected_units.update(capacity='uL', tray_rows='count', tray_columns='count', slot_count='count')
    require(set(spec['parameters']) == set(expected_units), 'Supported driving and derived parameters required')
    for key, definition in spec['parameters'].items():
        exact(definition, 'expression unit range', 'parameter')
        limits = definition['range']
        require(definition['unit'] == expected_units[key] and isinstance(limits, list) and len(limits) == 2
                and all(type(v) in (int, float) and math.isfinite(v) for v in limits)
                and 0 < limits[0] <= limits[1], 'Bounded parameter with declared unit required')
    articles = set()
    for variant, item in spec['variants'].items():
        exact(item, 'article overrides dimension_evidence unknown_measurements', 'variant')
        article = item['article']
        exact(article, 'manufacturer family catalog_number purity_grade filtered catalog_length_mm tips_per_tray trays_per_pack source_id locator', 'article')
        evidence(article); evidence(item['dimension_evidence'])
        require(all(isinstance(article[k], str) and article[k] for k in ('manufacturer', 'family', 'catalog_number', 'purity_grade')), 'Concrete article identity required')
        identity = (article['manufacturer'], article['catalog_number'])
        require(identity not in articles and article['filtered'] is False, 'Distinct unfiltered articles required')
        articles.add(identity)
        p = parameters(spec, variant)
        require(p['capacity'] == VARIANTS[variant] and (p['tray_rows'], p['tray_columns'], p['slot_count'], p['pitch']) == (8, 12, 96, 9), 'Requested volume and 8 by 12 system grid required')
        require(article['tips_per_tray'] == p['slot_count'] and type(article['trays_per_pack']) is int and article['trays_per_pack'] > 0, 'Article packing must match tray capacity')
        for key, value in p.items():
            lo, hi = spec['parameters'][key]['range']
            require(lo <= value <= hi, 'Parameter outside declared range: '+key)
        require(p['tip_length'] > p['collar_od'] > p['inlet_id'] > 0
                and p['collar_od'] >= p['body_diameter_callout'] > p['outlet_od'] > p['outlet_id'] > 0, 'Inconsistent nominal tip dimensions')
        require(p['strip_axis_span'] == (p['tray_rows']-1)*p['pitch'] and p['tray_axis_span_x'] == (p['tray_columns']-1)*p['pitch'], 'Grid spans must derive from pitch and counts')
        require(set(item['unknown_measurements']) == set(MEASUREMENTS), 'Explicit missing tip/pipette measurements required')
        for key, measurement in item['unknown_measurements'].items():
            exact(measurement, 'value unit source_id locator open_task', 'measurement')
            require(measurement['unit'] == MEASUREMENTS[key] and measurement['open_task'], 'Measurement unit and follow-up required')
            value = measurement['value']
            if value is None:
                require(measurement['source_id'] is None and measurement['locator'] is None, 'Unknown values cannot claim measurement evidence')
            else:
                require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'Finite nonnegative measurement required')
                evidence(measurement)
    geometry = spec['geometry']
    exact(geometry, 'tip strip tray box', 'geometry definition')
    exact(geometry['tip'], 'recipe length_parameter collar_diameter_parameter body_callout_parameter profile_complete body_callout_is_capture_maximum', 'tip landmarks')
    exact(geometry['strip'], 'recipe tip_count_parameter pitch_parameter physical_carrier_confirmed outer_length_mm outer_width_mm thickness_mm basis', 'logical strip')
    exact(geometry['tray'], 'recipe strip_count_parameter pitch_parameter pitch_source_id outer_length_mm outer_width_mm outer_height_mm wall_thickness_mm well_diameter_mm seat_offset_from_tip_mouth_mm basis', 'tray')
    exact(geometry['box'], 'recipe outer_length_mm outer_width_mm outer_height_mm wall_thickness_mm lid_thickness_mm basis', 'box')
    require((geometry['tip']['length_parameter'], geometry['tip']['collar_diameter_parameter'], geometry['tip']['body_callout_parameter'],
             geometry['strip']['tip_count_parameter'], geometry['strip']['pitch_parameter'], geometry['tray']['strip_count_parameter'], geometry['tray']['pitch_parameter'])
            == ('tip_length', 'collar_od', 'body_diameter_callout', 'tray_rows', 'pitch', 'tray_columns', 'pitch'), 'Supported recipe parameter bindings required')
    require(geometry['tip']['recipe'] == 'documented_dimension_landmarks/1'
            and geometry['strip']['recipe'] == 'logical_tip_column/1'
            and geometry['tray']['recipe'] == 'rectangular_tip_grid/1'
            and geometry['box']['recipe'] == 'unresolved_container/1', 'Supported tip/grid recipes required')
    require(geometry['tip']['profile_complete'] is False and geometry['tip']['body_callout_is_capture_maximum'] is False, 'Landmarks do not define a full tip or capture profile')
    for kind in ('strip', 'tray', 'box'):
        require(all(value is None for key, value in geometry[kind].items() if key.endswith('_mm')), 'Unimplemented physical packaging dimensions must remain null')
    require(geometry['strip']['physical_carrier_confirmed'] is None, 'A logical strip does not prove a detachable carrier')
    require(geometry['tray']['pitch_source_id'] in spec['sources'], 'Nominal pitch needs manufacturer system evidence')
    fit = spec['fit_to']
    exact(fit, 'id assembly grooves unknown_policy', 'collector binding')
    require(fit['id'] == 'tip-collector-t01' and fit['grooves'] == dict(zip(VARIANTS, ('S', 'M', 'L'))), 'Explicit T01 groove mapping required')
    bound = collector.load(assembly.validate_reference(fit['assembly']))
    require({g['id']: g['target_pipette_capacity_ul'] for g in bound['grooves']} == {'S': 10, 'M': 200, 'L': 1000}, 'Referenced collector capacities differ')
    require(len({t['id'] for t in spec['open_tasks']}) == len(spec['open_tasks']), 'Unique open tasks required')
    return spec


def slot_ids(spec, variant):
    p = parameters(spec, variant)
    return [f'{chr(65+r)}{c+1:02d}' for c in range(int(p['tray_columns'])) for r in range(int(p['tray_rows']))]


def fit_check(spec, variant, collector_spec=None):
    """Dimension-only assessment; nominal drawing callouts never fill tolerance gaps."""
    station = collector_spec if collector_spec is not None else collector.load(assembly.validate_reference(spec['fit_to']['assembly']))
    rule = station['fit_rule']; station_p = collector.parameters(station)
    p = parameters(spec, variant); lane = spec['fit_to']['grooves'][variant]
    width = station_p['groove_'+lane]
    measurements = spec['variants'][variant]['unknown_measurements']
    needed_tip = ('shaft_diameter_max', 'collar_diameter_min', 'access_gap_above_collar', 'vertical_running_clearance')
    needed_rule = ('shaft_diameter_max_mm', 'collar_diameter_min_mm', 'radial_running_clearance_mm', 'radial_capture_margin_mm', 'access_gap_above_collar_min_mm')
    missing = ['tip.'+k for k in needed_tip if measurements[k]['value'] is None]
    missing += ['T01.fit_rule.'+k for k in needed_rule if rule[k] is None]
    checks = {}
    if not missing:
        m = {k: measurements[k]['value'] for k in needed_tip}
        values = list(m.values()) + [rule[k] for k in needed_rule]
        require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values), 'Finite fit inputs required')
        checks = {
            'shaft_within_rule': m['shaft_diameter_max'] <= rule['shaft_diameter_max_mm'],
            'collar_within_rule': m['collar_diameter_min'] >= rule['collar_diameter_min_mm'],
            'shaft_clears_groove': rule['shaft_diameter_max_mm'] + 2*rule['radial_running_clearance_mm'] <= width,
            'collar_captured': width <= rule['collar_diameter_min_mm'] - 2*rule['radial_capture_margin_mm'],
            'sleeve_gap': m['access_gap_above_collar'] >= max(rule['access_gap_above_collar_min_mm'], station_p['fork_t'] + m['vertical_running_clearance']),
        }
    return {'status': 'open' if missing else 'passed' if all(checks.values()) else 'failed',
            'groove_id': lane, 'groove_width_mm': width, 'missing': missing, 'checks': checks,
            'nominal_collar_screen': {'collar_od_mm': p['collar_od'], 'diametral_excess_mm': p['collar_od']-width,
                                      'retaining_overlap_possible': p['collar_od'] > width,
                                      'basis': 'Nominal top-OD gauge only; not tolerance, contact, force or sleeve qualification.'},
            'qualified': False}


def compile_instance(spec, item, occupancy):
    """Derive all slot frames from a named variant and an explicit occupancy snapshot."""
    assembly.validate_instance(item)
    require(set(item) <= {'id', 'asset', 'host', 'xyz', 'yaw_deg', 'variant', 'pose', 'overrides'}
            and {'host', 'variant', 'pose'} <= set(item), 'Tip instance needs frame, variant and occupancy pose')
    require(not item.get('overrides'), 'Article dimensions require a sourced variant, not instance overrides')
    require(all(type(v) in (int, float) and math.isfinite(v) for v in item['xyz']), 'Finite numeric instance position required')
    variant = item['variant']; p = parameters(spec, variant)
    exact(occupancy, 'occupied_slots evidence', 'occupancy')
    exact(occupancy['evidence'], 'kind reference', 'occupancy evidence')
    require(occupancy['evidence']['kind'] in {'synthetic_fixture', 'owner_statement', 'measurement_record'}
            and isinstance(occupancy['evidence']['reference'], str) and occupancy['evidence']['reference'], 'Documented occupancy snapshot required')
    ids = slot_ids(spec, variant); occupied = occupancy['occupied_slots']
    require(isinstance(occupied, list) and all(isinstance(v, str) for v in occupied)
            and len(set(occupied)) == len(occupied) and set(occupied) <= set(ids), 'Unknown or duplicate occupied slot')
    pose = 'full' if len(occupied) == len(ids) else 'empty' if not occupied else 'partial'
    require(item['pose'] == pose, 'Occupancy state contradicts the explicit slot list')
    transform = layout.matrix(item, {})
    slots = []
    for identity in ids:
        row, column = ord(identity[0])-65, int(identity[1:])-1
        local = [column*p['pitch'], row*p['pitch'], 0]
        slots.append({'id': identity, 'strip_id': f'Strip{column+1:02d}', 'occupied': identity in occupied,
                      'tip_id': item['id']+'.'+identity if identity in occupied else None,
                      'mouth_mm': robot.transform(transform, local),
                      'outlet_mm': robot.transform(transform, local[:2]+[-p['tip_length']]) if identity in occupied else None})
    return {'id': item['id'], 'host': item['host'], 'variant': variant, 'pose': pose,
            'article': copy.deepcopy(spec['variants'][variant]['article']), 'parameters': p,
            'occupied_count': len(occupied), 'slots': slots, 'occupancy_evidence': copy.deepcopy(occupancy['evidence']),
            'fit_to_T01': fit_check(spec, variant), 'solid_geometry_ready': False,
            'strip_carrier_confirmed': False, 'physical_placement_qualified': False}


def compile_instances(path=INSTANCES):
    scene = json.loads(Path(path).read_text(encoding='utf-8'))
    exact(scene, 'format basis assets instances', 'instance composition')
    require(scene['format'] == 'solidcraftbot.tip-supply-instances/1', 'Tip instance composition required')
    sources = {key: load(assembly.validate_reference(ref)) for key, ref in scene['assets'].items()}
    result = []; seen = set()
    for entry in scene['instances']:
        exact(entry, 'assembly occupancy', 'placed supply')
        item = entry['assembly']
        require(item['id'] not in seen and item['asset'] in sources, 'Unique instance and known source required')
        seen.add(item['id'])
        result.append(compile_instance(sources[item['asset']], item, entry['occupancy']))
    return result
