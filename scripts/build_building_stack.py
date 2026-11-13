"""Independent native five-level presentation model; no surveyed building claims."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time

import building_stack as model
import build_relative_floorplan as floor
import build_extraction_kit_station as common
import tool_paths

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.building-stack-build/1'
NOTICE = 'Presentation mm: XY uncalibrated and fitted to an unmeasured L01 concept; vertical clear height owner-assumed, slabs illustrative'
write, relative = common.write, common.relative


def snapshot(spec, source):
    paths = [source, Path(__file__), ROOT/'scripts/build_building_stack_freecad.py',
             ROOT/'scripts/build_relative_floorplan.py', ROOT/'scripts/build_extraction_kit_station.py',
             ROOT/'scripts/extraction_kit_station.py', ROOT/'scripts/build_tube_carrier_freecad.py',
             ROOT/'scripts/build_neutral_freecad.py', ROOT/'scripts/robot_cameras.py',
             ROOT/'scripts/freecad/solidcraftbot_freecad.py', ROOT/'scripts/freecad/persist_station_view.py',
             ROOT/'scripts/freecad/persist_view.py', ROOT/'scripts/tool_paths.py', ROOT/'scripts/building_roof.py', *model.source_dependencies(spec)]
    result = {}
    for path in paths:
        path = Path(path).resolve(); name = relative(path)
        if not name.startswith(('model/', 'scripts/', 'tests/fixtures/')) or path.suffix not in {'.py', '.json'}:
            raise ValueError('Only public model/code dependencies may enter the building proof')
        result[name] = common.robot_spec.digest(path)
    return result


def prism_volume(probe):
    points = probe['points_mm']; depth = probe['depth_mm']
    if len(points) < 3 or any(len(point) != 2 for point in points):
        raise ValueError('A planar polygon prism is required')
    values = [v for point in points for v in point]+[probe['offset_mm'], depth]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or depth <= 0:
        raise ValueError('Finite positive presentation prism required')
    area = abs(math.fsum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1])))/2
    if area <= 0: raise ValueError('Positive prism footprint required')
    return area*depth


def z_checks(geometry, contract):
    bodies = {body['body']: body for body in geometry}; checks = []
    levels = contract['levels']
    if len(levels) != 5 or len({level['id'] for level in levels}) != 5:
        raise ValueError('Exactly five distinct referenced levels required')
    seen = set()
    for level in levels:
        walls, floors = level['wall_bodies'], level['floor_bodies']
        if not walls or not floors or seen.intersection(walls+floors): raise ValueError('Complete disjoint level body manifests required')
        seen.update(walls+floors)
        passed = True
        for name in floors:
            bb = bodies[name]['bbox']
            passed &= abs(bb['min'][2]-level['slab_bottom_mm']) < 1e-6 and abs(bb['max'][2]-level['slab_top_mm']) < 1e-6
        for name in walls:
            bb = bodies[name]['bbox']
            passed &= bb['min'][2] >= level['z_mm']-1e-6 and abs(bb['max'][2]-level['clear_top_mm']) < 1e-6
        checks.append({'id': level['id'], 'passed': bool(passed), 'floor_bodies': floors, 'wall_bodies': walls,
                       'slab_bottom_presentation_mm': level['slab_bottom_mm'], 'slab_top_presentation_mm': level['slab_top_mm'],
                       'clear_top_presentation_mm': level['clear_top_mm']})
    ground = contract['ground_fill_probe']
    expected = (seen | set(ground.get('target_bodies', [ground.get('target_body')])) | set(contract['marker_body_ids'])
                | set(contract.get('furnishings', {}).get('body_ids', [])) | set(contract.get('exterior', {}).get('body_ids', [])) | set(contract.get('circulation', {}).get('body_ids', [])) | set(contract.get('roof', {}).get('body_ids', [])))
    if expected != set(bodies): raise ValueError('Every native body must belong to an explicit scoped role')
    for a, b in zip(levels, levels[1:]):
        gap = b['slab_bottom_mm']-a['slab_top_mm']
        checks.append({'id': a['id']+'_to_'+b['id'], 'passed': abs(gap-contract['assumed_dimensions']['clear_height_mm']) < 1e-6,
                       'assumed_clear_interval_presentation_mm': gap})
    if contract.get('exterior'):
        ext = contract['exterior']
        for name in ext['terrain_body_ids']:
            bb = bodies[name]['bbox']
            checks.append({'id': name+'_Grade', 'passed': abs(bb['max'][2]-ext['grade_z_mm']) < 1e-6 and abs(bb['min'][2]-ext['terrain_bottom_mm']) < 1e-6})
        bb = bodies[ext['frame_body_id']]['bbox']
        checks.append({'id':'FoyerFacade_Height','passed':abs(bb['min'][2]-ext['grade_z_mm']) < 1e-6 and abs(bb['max'][2]-ext['facade_top_mm']) < 1e-6})
    return checks


def coverage(spec, p, geometry):
    contract = model.interfaces(spec, p); z = z_checks(geometry, contract)
    names = {body['body'] for body in geometry}
    openings = contract['opening_probes']; holes = contract['atrium_prisms']; ground = contract['ground_fill_probe']
    ids = [probe['id'] for probe in openings+holes+[ground]]
    if len(ids) != len(set(ids)) or len(holes) != 3 or not openings:
        raise ValueError('Complete unique opening/upper-atrium/ground probes required')
    all_walls = {name for level in contract['levels'] for name in level['wall_bodies']}
    visible_walls = set(contract['wall_visibility_ids'])
    allowed_walls = all_walls | set(contract.get('circulation', {}).get('wall_bridge_ids', []))
    if visible_walls != allowed_walls: raise ValueError('Wall visibility manifest differs from native wall roles')
    for probe in openings:
        prism_volume(probe)
        if probe['target_body'] not in all_walls | set(contract.get('exterior', {}).get('door_leaves', {}).values()): raise ValueError('Opening probe must target a modeled wall')
    for level, probe in zip([v for v in contract['levels'] if v['id'].startswith('OG')], holes):
        prism_volume(probe)
        if set(probe['target_bodies']) != set(level['floor_bodies']): raise ValueError('Atrium proof must cover every upper-level floor')
        if abs(probe['offset_mm']-level['slab_bottom_mm']) > 1e-6 or abs(probe['depth_mm']-(level['slab_top_mm']-level['slab_bottom_mm'])) > 1e-6:
            raise ValueError('Atrium probe must span the full upper slab depth')
    volume = prism_volume(ground)
    targets = ground.get('target_bodies', [ground.get('target_body')])
    if not targets or not set(targets) <= names or abs(volume-ground['expected_volume_mm3']) > max(1e-5, volume*1e-9):
        raise ValueError('Ground closure proof must use its complete source polygon')
    if ground.get('expectation') == 'union_filled' and not set(targets) <= set(next(v for v in contract['levels'] if v['id'] == 'EG')['floor_bodies']):
        raise ValueError('Actual EG coverage must reference its own native floor bodies')
    circulation_geometry(contract, geometry)
    circulation_probe_specs(contract)
    roof_geometry(contract, geometry)
    return contract, z


def circulation_geometry(contract, geometry):
    circ = contract.get('circulation')
    if not circ: return []
    bodies = {body['body']: body for body in geometry}; levels = contract['levels']
    elevator = circ['elevator']; expected_doors = {'KG': ['inward'], 'EG': ['outward', 'inward'], 'OG1': ['outward'], 'OG2': ['outward'], 'OG3': ['outward']}
    if elevator['doors_by_level'] != expected_doors:
        raise ValueError('Elevator door policy must distinguish EG and upper levels')
    ports = elevator['ports']; active = [port for port in ports if port['active'] is True]
    inactive = [port for port in ports if port['active'] is False]
    if (len(ports) != 10 or len(active) != 6 or len(inactive) != 4
            or {(port['level_id'], port['side']) for port in active} != {(level, side) for level, sides in expected_doors.items() for side in sides}
            or {(port['level_id'], port['side']) for port in inactive} != {(level['id'], side) for level in levels for side in ('inward', 'outward') if side not in expected_doors[level['id']]}):
        raise ValueError('Exactly six active and four explicitly closed elevator faces required')
    closed_targets = {probe['target_body'] for probe in circ['closed_door_probes']}
    if closed_targets != {port['level_id']+'__Wall_'+port['wall'] for port in inactive}:
        raise ValueError('Every inactive upper inward face requires its associated wall-material witness')
    deferred = elevator['deferred_stops']
    if deferred:
        raise ValueError('No unmodeled basement stops may remain')
    if len(circ['stairs']) != 1 or circ['stairs'][0]['area'] != 'R3_028':
        raise ValueError('Only the owner-confirmed right stair core R3_028 may connect storeys')
    level_z = {level['id']: level['z_mm'] for level in levels}
    pairs = {(a['id'], b['id']) for a, b in zip(levels, levels[1:])}
    checks = []
    for stair in circ['stairs']:
        connectors = stair['connectors']
        if len(connectors) != len(pairs) or {(c['from_level'], c['to_level']) for c in connectors} != pairs:
            raise ValueError('Each stair must connect all three adjacent-storey pairs')
        if not {connector['body_id'] for connector in connectors} <= set(stair['body_ids']):
            raise ValueError('Every stair connector must belong to its separate stair body group')
        planned = stair['planned_connectors']
        if planned:
            raise ValueError('All KG–OG3 stair connectors must have geometry')
        if stair['served_extent'] != {'from_level': 'KG', 'to_level': 'OG3'}:
            raise ValueError('The stair served extent must distinguish intended KG service from modeled storeys')
        for connector in connectors:
            body = bodies[connector['body_id']]; lower = level_z[connector['from_level']]; upper = level_z[connector['to_level']]
            checks.append({'id': connector['body_id']+'_end_levels',
                           'passed': body['bbox']['min'][2] <= lower+1e-6 and body['bbox']['max'][2] >= upper-1e-6,
                           'from_level': connector['from_level'], 'to_level': connector['to_level'],
                           'scope': 'One native closed connector solid spanning the source endpoints; contact witnesses checked separately'})
    external = circ.get('external_stairs', [])
    external_ids = set()
    if external:
        require_external = len(external) == 1 and external[0]['area'] == 'R3_017' and external[0]['classification'] == 'external_metal'
        if not require_external or 'roof' not in contract:
            raise ValueError('The external metal staircase is a distinct source-referenced roof-to-EG system')
        ext = external[0]; ordered = [level['id'] for level in levels if level['id'] != 'KG']+['ROOF']; pairs_ext = set(zip(ordered, ordered[1:]))
        if ext['served_extent'] != {'from_level': 'EG', 'to_level': 'ROOF'} or len(ext['connectors']) != len(pairs_ext) or {(c['from_level'], c['to_level']) for c in ext['connectors']} != pairs_ext:
            raise ValueError('External stairs must span EG to Roof without a basement segment')
        external_ids = set(ext['body_ids']); level_z['ROOF'] = contract['roof']['roof_z_mm']
        if not {c['body_id'] for c in ext['connectors']} <= external_ids:
            raise ValueError('Every external connector requires its own native body role')
        for connector in ext['connectors']:
            bb = bodies[connector['body_id']]['bbox']
            checks.append({'id': connector['body_id']+'_end_levels', 'from_level': connector['from_level'], 'to_level': connector['to_level'],
                           'passed': bb['min'][2] <= level_z[connector['from_level']]+1e-6 and bb['max'][2] >= level_z[connector['to_level']]-1e-6,
                           'scope': 'One native closed external connector spanning declared endpoints; no KG or fire-safety qualification'})
    shaft_ids = elevator['shaft_body_ids']; cabin_ids = elevator['cabin_body_ids']
    if not shaft_ids or not cabin_ids or not set(shaft_ids+cabin_ids) <= set(circ['body_ids']):
        raise ValueError('Explicit existing shaft and EG cabin bodies required')
    if not set(circ['detail_visibility_ids']) <= set(bodies) or not set(shaft_ids+cabin_ids) <= set(circ['detail_visibility_ids']):
        raise ValueError('Circulation detail must preserve the existing elevator')
    lift_ids = set(shaft_ids+cabin_ids+elevator['door_frame_body_ids'])
    stair_ids = {name for stair in circ['stairs'] for name in stair['body_ids']}
    groups = [elevator['component_id']]+[stair['component_id'] for stair in circ['stairs']+external]
    if (lift_ids & stair_ids or lift_ids & external_ids or stair_ids & external_ids or len(groups) != len(set(groups))
            or not (lift_ids | stair_ids | external_ids) <= set(circ['body_ids'])):
        raise ValueError('The standalone elevator and right stair must have separate explicit body groups')
    if elevator['served_extent'] != {'from_level': 'KG', 'to_level': 'OG3'}:
        raise ValueError('The elevator served extent must retain the unmodeled intended basement stop')
    checks.append({'id': 'separate_stair_and_elevator_groups',
                   'passed': (all(bodies[name].get('component') == elevator['component_id'] for name in lift_ids)
                              and all(bodies[name].get('component') == stair['component_id'] for stair in circ['stairs']+external for name in stair['body_ids'])),
                   'elevator_component': elevator['component_id'], 'stair_components': [stair['component_id'] for stair in circ['stairs']],
                   'external_stair_components': [stair['component_id'] for stair in external],
                   'scope': 'Separate source body identities and measured rigid-component groups; no mechanical or navigation qualification'})
    checks.append({'id': 'circulation_within_modeled_extent',
                   'passed': all(bodies[name]['bbox']['min'][2] >= levels[0]['slab_bottom_mm']-1e-6 for name in circ['body_ids']),
                   'deferred_stops': deferred, 'planned_stair_connectors': [entry for stair in circ['stairs'] for entry in stair['planned_connectors']],
                   'scope': 'No circulation geometry below the lowest modeled slab'})
    return checks


def circulation_probe_specs(contract):
    circ = contract.get('circulation')
    if not circ: return []
    stairs = circ['stairs']+circ.get('external_stairs', [])
    connectors = [connector for stair in stairs for connector in stair['connectors']]
    connector_count = len(connectors)
    expected_holes = sum(connector.get('slab_hole_probe_id', 'legacy') is not None for connector in connectors)
    expected_counts = {'door_probes': 6, 'closed_door_probes': 4, 'slab_hole_probes': expected_holes,
                       'connection_witnesses': connector_count*3, 'shaft_witnesses': 4,
                       'external_access_witnesses': sum(len(stair['connectors']) for stair in circ.get('external_stairs', []))}
    if any(len(circ.get(key, [])) != count for key, count in expected_counts.items()):
        raise ValueError('Complete current-stop, stair-aperture and connection witness coverage required')
    if connectors and all('slab_hole_probe_id' in connector for connector in connectors):
        if {connector['slab_hole_probe_id'] for connector in connectors if connector['slab_hole_probe_id'] is not None} != {probe['id'] for probe in circ['slab_hole_probes']}:
            raise ValueError('Native slab-hole proofs must match the explicitly declared connector aperture IDs')
    result = []
    for category, probes in [('circulation_door', circ['door_probes']), ('closed_inward_door', circ['closed_door_probes']),
                             ('stair_slab_hole', circ['slab_hole_probes']), ('stair_connection', circ['connection_witnesses']),
                             ('shaft_continuity', circ['shaft_witnesses']), ('external_access', circ.get('external_access_witnesses', []))]:
        for probe in probes:
            volume = prism_volume(probe)
            targets = probe.get('target_bodies', [probe.get('target_body')])
            if (not targets or any(not isinstance(name, str) or not name for name in targets)
                    or len(targets) != len(set(targets))):
                raise ValueError('Distinct explicit native witness targets required')
            if category in {'circulation_door', 'stair_slab_hole'}:
                expected = {target: 0. for target in targets}
            elif category == 'closed_inward_door':
                expected = {probe['target_body']: probe['expected_volume_mm3']}
            else:
                expected = probe['expected_volumes_mm3']
            if not expected or set(expected) != set(targets):
                raise ValueError('Every circulation witness requires explicit target coverage')
            if category not in {'circulation_door', 'stair_slab_hole'}:
                if any(type(value) not in (int, float) or not math.isfinite(value) or abs(value-volume) > max(1e-5, volume*1e-9) for value in expected.values()):
                    raise ValueError('Positive material witnesses must be fully covered by every declared target')
            result.append({'category': category, 'probe': probe, 'expected': expected})
    ids = [item['probe']['id'] for item in result]
    if len(ids) != len(set(ids)):
        raise ValueError('Unique circulation probe identities required')
    return result


def material_witness(inspection, target, witness, expected):
    required = {'checked', 'count', 'interferences', 'unchecked', 'truncated', 'budget_exceeded', 'pairs_not_checked', 'skipped_pairs'}
    if (not required <= set(inspection) or inspection['checked'] != 2 or inspection['count'] != 1
            or len(inspection['interferences']) != 1 or inspection['unchecked'] or inspection['truncated'] is not False
            or inspection['budget_exceeded'] is not False or inspection['pairs_not_checked'] or inspection['skipped_pairs']):
        raise ValueError('Complete positive material witness evidence required')
    hit = inspection['interferences'][0]
    if {hit['a'], hit['b']} != {target, witness}:
        raise ValueError('Material witness refers to another body pair')
    actual = hit['volume_mm3']; tolerance = max(1e-5, expected*1e-7)
    return {'passed': type(actual) in (int, float) and math.isfinite(actual) and abs(actual-expected) <= tolerance,
            'expected_presentation_mm3': expected, 'intersection_presentation_mm3': actual,
            'tolerance_presentation_mm3': tolerance, 'scope': 'Witness material coverage, not whole-target volume equality'}


def union_coverage(inspection, targets, witness, expected):
    """Prove a prism is filled by explicitly inspected, nonoverlapping targets."""
    required = {'checked', 'count', 'interferences', 'unchecked', 'truncated', 'budget_exceeded', 'pairs_not_checked', 'skipped_pairs'}
    if (not targets or len(targets) != len(set(targets)) or witness in targets or not required <= set(inspection)
            or inspection['checked'] != len(targets)+1 or inspection['count'] != len(inspection['interferences'])
            or inspection['unchecked'] or inspection['truncated'] is not False or inspection['budget_exceeded'] is not False
            or inspection['pairs_not_checked'] or inspection['skipped_pairs']):
        raise ValueError('Complete native target-union pair coverage required')
    volumes = {target: 0. for target in targets}; overlaps = []; seen = set(); names = set(targets)|{witness}
    for hit in inspection['interferences']:
        a, b, volume = hit['a'], hit['b'], hit['volume_mm3']; pair = frozenset((a, b))
        if (a == b or not {a, b} <= names or pair in seen or type(volume) not in (int, float) or not math.isfinite(volume) or volume < 0):
            raise ValueError('Unambiguous finite native union intersections required')
        seen.add(pair)
        if witness in pair:
            volumes[b if a == witness else a] = volume
        elif volume > 1e-5:
            overlaps.append(hit)
    total = math.fsum(volumes.values()); tolerance = max(1e-5, expected*1e-7)
    return {'passed': not overlaps and abs(total-expected) <= tolerance, 'expected_presentation_mm3': expected,
            'intersection_sum_presentation_mm3': total, 'target_intersections_presentation_mm3': volumes,
            'target_pair_overlaps': overlaps, 'tolerance_presentation_mm3': tolerance,
            'scope': 'This named target union only; complete pair checks exclude volume double-counting, not global building interference'}


def shell_area_volume(probe, barrel):
    """Exact circle antiderivatives integrated over the full XY area boundary.

    Green's theorem reduces integral(delta_z(y) dx dy) to linear edge
    integrals. This preserves concavities and is not a bounding-box estimate.
    Evaluation is binary64; native comparisons retain an explicit tolerance.
    """
    prism_volume(probe)
    if barrel['axis'] != 'X' or barrel['profile_axis'] != 'Y':
        raise ValueError('The full-area shell integral requires the declared X/Y barrel contract')
    radius, inner, cy, cz = [barrel[key] for key in ('radius_mm', 'inner_radius_mm', 'center_cross_mm', 'center_z_mm')]
    if not all(type(v) in (int,float) and math.isfinite(v) for v in (radius,inner,cy,cz)) or not 0 < inner < radius:
        raise ValueError('Finite positive inner/outer cylinder radii required')
    points=probe['points_mm']; xorigin=(min(p[0]for p in points)+max(p[0]for p in points))/2
    if any(abs(y-cy) >= inner or cz+math.sqrt(inner*inner-(y-cy)**2) < probe['offset_mm'] for x,y in points) or probe['offset_mm']+probe['depth_mm'] < cz+radius:
        raise ValueError('The complete upper shell must lie within the full-area probe height')
    def primitives(r,v):
        root=math.sqrt(max(0.,r*r-v*v))
        return .5*(v*root+r*r*math.asin(v/r)), -(root**3)/3
    terms=[]
    for a,b in zip(points,points[1:]+points[:1]):
        va,vb=a[1]-cy,b[1]-cy
        if va==vb:continue
        slope=(b[0]-a[0])/(vb-va);intercept=a[0]-xorigin-slope*va
        oa,ob,ia,ib=primitives(radius,va),primitives(radius,vb),primitives(inner,va),primitives(inner,vb)
        terms.append(slope*math.fsum([ob[1],-oa[1],-ib[1],ia[1]])+intercept*math.fsum([ob[0],-oa[0],-ib[0],ia[0]]))
    result=abs(math.fsum(terms))
    if not math.isfinite(result) or not 0 < result <= prism_volume(probe):
        raise ValueError('Positive finite full-area shell volume required')
    return result


def roof_geometry(contract, geometry):
    roof = contract.get('roof')
    if not roof: return []
    bodies = {body['body']: body for body in geometry}; checks = []
    glass_ids=roof.get('glass_body_ids',[roof['glass_body_id']])
    if set(roof['body_ids']) != set(roof['opaque_body_ids'])|set(roof['guard_body_ids'])|set(glass_ids):
        raise ValueError('Complete disjoint native roof roles required')
    for name in roof['opaque_body_ids']:
        bb = bodies[name]['bbox']; checks.append({'id': name+'_slab_z', 'passed': abs(bb['min'][2]-roof['slab_bottom_mm']) <= 1e-5 and abs(bb['max'][2]-roof['slab_top_mm']) <= 1e-5})
    for name in roof['guard_body_ids']:
        bb = bodies[name]['bbox']; checks.append({'id': name+'_guard_z', 'passed': abs(bb['min'][2]-roof['roof_z_mm']) <= 1e-5 and abs(bb['max'][2]-roof['roof_z_mm']-roof['guard']['height_mm']) <= 1e-5})
    bb = bodies[roof['glass_body_id']]['bbox']; barrel = roof['barrel']
    if barrel['axis']=='X':
        max_y=max(abs(y-barrel['center_cross_mm'])for y in barrel['y_bounds_mm'])
        lower=barrel['center_z_mm']+math.sqrt(barrel['inner_radius_mm']**2-max_y**2)
    else:lower=roof['roof_z_mm']
    expected = [barrel['x_bounds_mm'], barrel['y_bounds_mm'], [lower, barrel['crown_z_mm']]]
    checks.append({'id': 'RoofGlass_CrownAndEaveBounds', 'passed': all(abs(bb[edge][i]-expected[i][j]) <= 1e-5 for i in range(3) for j, edge in enumerate(('min', 'max'))),
                   'scope': 'Native bounding extents; separate material and hollow-interior probes check the actual cap'})
    if roof.get('glass_skirt_body_id'):
        skirt=bodies[roof['glass_skirt_body_id']]['bbox']
        checks.append({'id':'RoofGlass_SkirtBounds','passed':abs(skirt['min'][2]-roof['roof_z_mm'])<=1e-5 and skirt['max'][2]<=barrel['crown_z_mm']+1e-5
                       and all(abs(skirt[edge][i]-expected[i][j])<=1e-5 for i in range(2)for j,edge in enumerate(('min','max'))),
                       'scope':'Separate bounded facetted closure; the cap remains analytically cylindrical'})
    aperture_by_area={probe['area_id']:probe for probe in roof.get('aperture_coverage_probes',[])}
    for deck in roof.get('local_opaque_exceptions',[]):
        target=bodies[deck['body_id']];volume=prism_volume(deck);bb=target['bbox'];tol=max(1e-5,volume*1e-7)
        expected_bb=[[min(q[i]for q in deck['points_mm']),max(q[i]for q in deck['points_mm'])]for i in range(2)]+[[deck['offset_mm'],deck['offset_mm']+deck['depth_mm']]]
        area=aperture_by_area.get(deck['area_id']);full=abs(prism_volume(area)/area['depth_mm']*deck['depth_mm'])if area else 0
        checks.append({'id':deck['body_id']+'_LocalAccessDeckBounds','passed':abs(target['volume_mm3']-volume)<=tol and volume<full-tol
                       and all(abs(bb[edge][i]-expected_bb[i][j])<=1e-5 for i in range(3)for j,edge in enumerate(('min','max'))),
                       'source_opening':deck['source_opening'],'area_id':deck['area_id'],'local_volume_mm3':volume,'full_corridor_slab_volume_mm3':full,
                       'scope':'This explicitly bounded access deck only; a complete corridor roof slab cannot satisfy this check'})
    checks.append({'id': 'Roof_SeparateGroundedGroup', 'passed': all(bodies[name].get('component') == roof['component_id'] for name in roof['body_ids'])})
    return checks


def roof_probe_specs(contract):
    roof = contract.get('roof')
    if not roof: return []
    groups = [('roof_eave_support', roof['eave_support_probes']), ('roof_material', roof['material_probes']), ('roof_empty', roof['empty_probes'])]
    if not groups[0][1] or len(groups[1][1]) < 3 or len(groups[2][1]) < 2:
        raise ValueError('Complete declared roof eave, crown, hollow-interior and guard-gap probe coverage required')
    result = []
    for category, probes in groups:
        for probe in probes:
            volume = prism_volume(probe); targets = probe['target_bodies']; mode = probe['expectation']
            if not targets or len(set(targets)) != len(targets) or not set(targets) <= set(roof['body_ids']):
                raise ValueError('Explicit native roof probe targets required')
            expected_mode = {'roof_eave_support': 'union_filled', 'roof_material': 'filled', 'roof_empty': 'empty'}[category]
            if mode != expected_mode or (mode != 'empty' and abs(probe['expected_volume_mm3']-volume) > max(1e-5, volume*1e-9)):
                raise ValueError('Roof probes must preserve their complete source-prism volume')
            result.append({'category': category, 'probe': probe, 'expected': {target: 0. if mode == 'empty' else volume for target in targets}})
    corridors=roof.get('corridor_coverage_probes',[])
    if corridors:
        if {probe['area_id']for probe in corridors}!=set(roof['covered_corridor_area_ids']) or len(corridors)!=4:
            raise ValueError('Every one of the four covered source corridors requires a full-area native cap probe')
        for probe in corridors:
            if probe['target_bodies']!=[roof['glass_body_id']]:raise ValueError('Full-area circle integral must target only the analytic cap')
            volume=shell_area_volume(probe,roof['barrel'])
            result.append({'category':'roof_glass_area_coverage','probe':probe,'expected':{roof['glass_body_id']:volume},
                           'method':'Circle-shell Green integral over the complete source polygon; binary64 comparison with explicit native tolerance'})
    if len({item['probe']['id'] for item in result}) != len(result):
        raise ValueError('Unique roof proof identities required')
    return result


def corridor_roof_checks(contract, checks, geometry_checks):
    roof=contract.get('roof',{});coverage=roof.get('corridor_coverage_probes',[])
    if not coverage:return []
    expected=set(roof['covered_corridor_area_ids']);apertures={p['area_id']:p for p in roof['aperture_coverage_probes']}
    by_id={item['id']:item for item in checks};bounds={item['id']:item for item in geometry_checks};result=[]
    if len(coverage)!=4 or {p['area_id']for p in coverage}!=expected or not expected<=set(apertures):
        raise ValueError('Four actual source-corridor area proofs required')
    for probe in coverage:
        area=probe['area_id'];empty=apertures[area]
        exceptions=[e for e in roof.get('local_opaque_exceptions',[])if e['area_id']==area]
        deck_pass=all(bounds[e['body_id']+'_LocalAccessDeckBounds']['passed']for e in exceptions)
        result.append({'area_id':area,'glass_probe_id':probe['id'],'opaque_aperture_probe_id':empty['id'],
                       'passed':by_id[probe['id']]['passed'] and by_id[empty['id']]['passed'] and deck_pass,
                       'local_access_deck_exceptions':[e['body_id']for e in exceptions],
                       'scope':'Executed full source-polygon cap volume comparison and opaque aperture; explicitly bounded access deck only'})
    return result


def positive_ground(inspection, target, witness, expected, body_volume):
    required = {'checked', 'count', 'interferences', 'unchecked', 'truncated', 'budget_exceeded', 'pairs_not_checked', 'skipped_pairs'}
    if (not required <= set(inspection) or inspection['checked'] != 2 or inspection['count'] != 1
            or len(inspection['interferences']) != 1 or inspection['unchecked'] or inspection['truncated'] is not False
            or inspection['budget_exceeded'] is not False or inspection['pairs_not_checked'] or inspection['skipped_pairs']):
        raise ValueError('Complete native ground coverage evidence required')
    hit = inspection['interferences'][0]
    if {hit['a'], hit['b']} != {target, witness}: raise ValueError('Wrong ground coverage body pair')
    actual = hit['volume_mm3']; tolerance = max(1e-5, expected*1e-7)
    return {'passed': math.isfinite(actual) and abs(actual-expected) <= tolerance and abs(body_volume-expected) <= tolerance,
            'expected_presentation_mm3': expected, 'intersection_presentation_mm3': actual,
            'body_volume_presentation_mm3': body_volume, 'tolerance_presentation_mm3': tolerance}


def with_native_groups(geometry, listing):
    """Bind SC measurements to its read-only native component.list result."""
    if not isinstance(listing, dict) or not isinstance(listing.get('components'), list):
        raise ValueError('Native SolidCraft component listing required')
    groups = {}; component_names = set(); component_ids = set()
    for group in listing['components']:
        if group['name'] in component_names or group['id'] in component_ids or not isinstance(group.get('bodies'), list):
            raise ValueError('Unique explicit native component/body listings required')
        component_names.add(group['name']); component_ids.add(group['id'])
        if group['bodies']:
            occurrences = group.get('occurrences', [])
            if len(occurrences) != 1 or occurrences[0].get('grounded') is not True or occurrences[0].get('parent') != 0:
                raise ValueError('Each static building component requires one grounded root occurrence')
        for name in group['bodies']:
            if not isinstance(name, str) or name in groups:
                raise ValueError('Native bodies must belong to exactly one component')
            groups[name] = group['name']
    if set(groups) != {body['body'] for body in geometry}:
        raise ValueError('Native component listing does not cover every measured body')
    return [{**body, 'component': groups[body['body']]} for body in geometry]


def sc_audit(args, spec, p, native, out, geometry, paths):
    contract, z = coverage(spec, p, geometry); commands = [{'command': 'component.list', 'params': {'compact': True, 'bodies': True}}]; records = []
    unions = [item['probe'] for item in roof_probe_specs(contract) if item['probe']['expectation'] == 'union_filled']
    for category, probes in [('opening', contract['opening_probes']), ('atrium_floor_hole', contract['atrium_prisms']), ('ground_fill', [contract['ground_fill_probe']]), ('roof_eave_support', unions)]:
        for index, probe in enumerate(probes):
            name = 'StackProbe_'+category+'_'+str(index)
            if name in {b['body'] for b in geometry}: raise ValueError('Probe identity collision')
            targets = probe.get('target_bodies', [probe.get('target_body')])
            part = floor.probe_commands({**probe, 'target_body': targets[0]}, name)
            part[-1]['params']['bodies'] = [name]+targets
            commands.extend(part); records.append((category, probe, name, len(commands)-1, targets))
    circulation_records = []
    pair_specs = circulation_probe_specs(contract)+[item for item in roof_probe_specs(contract) if item['probe']['expectation'] != 'union_filled']
    for index, item in enumerate(pair_specs):
        probe = item['probe']; name = 'CirculationProbe_'+str(index); targets = list(item['expected'])
        commands.extend(floor.probe_commands({**probe, 'target_body': targets[0]}, name)[:-1])
        indices = {}
        for target in targets:
            commands.append({'command': 'inspect.interference', 'params': {'bodies': [name, target]}})
            indices[target] = len(commands)-1
        circulation_records.append((item, name, indices))
    script, result = out/'native-probes.commands.json', out/'native-probes.solidcraft.json'
    write(script, {'commands': commands}); before = common.robot_spec.digest(native)
    subprocess.run([args.solidcraft_cli, 'run', str(script), '--in', str(native), '--results', '--quiet', '--json-out', str(result)],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    if common.robot_spec.digest(native) != before: raise ValueError('Native audit modified saved building')
    raw = json.loads(result.read_text())
    if not isinstance(raw, list) or len(raw) != len(commands): raise ValueError('Incomplete consolidated native probe output')
    geometry = with_native_groups(geometry, raw[0])
    checks = []; volumes = {b['body']: b['volume_mm3'] for b in geometry}
    for category, probe, name, index, targets in records:
        check = (union_coverage(raw[index], targets, name, prism_volume(probe)) if probe.get('expectation') == 'union_filled'
                 else positive_ground(raw[index], targets[0], name, prism_volume(probe), volumes[targets[0]]) if category == 'ground_fill'
                 else common.check_solidcraft_interference([raw[index]], len(targets)+1))
        checks.append({'id': probe['id'], 'category': category, 'targets': targets, 'passed': check['passed'], 'evidence': check})
    for item, name, indices in circulation_records:
        evidence = {target: (common.check_solidcraft_interference([raw[index]], 2) if item['expected'][target] == 0
                            else material_witness(raw[index], target, name, item['expected'][target]))
                    for target, index in indices.items()}
        checks.append({'id': item['probe']['id'], 'category': item['category'], 'targets': list(indices),
                       'passed': all(check['passed'] for check in evidence.values()), 'target_evidence': evidence,
                       **({'area_id':item['probe']['area_id'],'method':item['method']}if item['category']=='roof_glass_area_coverage'else{})})
    circ_geometry = circulation_geometry(contract, geometry)
    roof_checks = roof_geometry(contract, geometry)
    corridors=corridor_roof_checks(contract,checks,roof_checks)
    paths.update(native_probe_commands=script, solidcraft_probes=result)
    return {'passed': all(c['passed'] for c in checks+z+circ_geometry+roof_checks+corridors), 'z_checks': z, 'probe_checks': checks,
            'circulation_geometry_checks': circ_geometry, 'roof_geometry_checks': roof_checks, 'native_components': raw[0],
            'corridor_roof_checks':corridors,'native_corridor_roof_checks_passed':bool(corridors)and all(c['passed']for c in corridors),
            'scope': 'Associated openings, upper floor holes, ground coverage, circulation witnesses and named roof cap/eave/guard checks only; no route, headroom or global interference qualification'}


def camera(geometry, *, atrium=False):
    lo = [min(b['bbox']['min'][i] for b in geometry) for i in range(3)]; hi = [max(b['bbox']['max'][i] for b in geometry) for i in range(3)]
    dx, dy, dz = [b-a for a, b in zip(lo, hi)]; yaw, pitch, fov = -.8, (.62 if atrium else .48), .6
    width = abs(math.cos(yaw))*dx+abs(math.sin(yaw))*dy; depth = abs(math.sin(yaw))*dx+abs(math.cos(yaw))*dy
    span = max(width/(1800/1400), dz*math.cos(pitch)+depth*math.sin(pitch))
    return {'target': [(a+b)/2 for a,b in zip(lo,hi)], 'yaw': yaw, 'pitch': pitch, 'distance': span*1.15/(2*math.tan(fov/2))+depth/2, 'fov': fov}


def build(args):
    started = time.monotonic(); source = Path(args.source).resolve(); source_name = relative(source)
    model.SOURCE = source; digest = common.robot_spec.digest(source); spec = model.load(source); p = model.parameters(spec)
    expanded = model.expanded(spec,p); contract = model.interfaces(spec,p); pins = snapshot(spec,source)
    if pins[source_name] != digest or expanded['joints']: raise ValueError('Source drift or non-static building')
    common.verify_pins(pins)
    stem = 'building-stack-'+digest[:12]; revision = stem; number = 1
    while any((ROOT/top/revision).exists() for top in ('cad/generated','exports/generated','renders')):
        number += 1; revision = stem+'-r'+str(number)
    cad,out,render = [ROOT/top/revision for top in ('cad/generated','exports/generated','renders')]
    for folder in (cad,out,render): folder.mkdir(parents=True)
    paths = {'case':out/'overview.case.json'}; write(paths['case'],{'source':source_name,'source_sha256':digest,'source_files_sha256':pins})
    print('Building stack: '+args.backend+'; '+NOTICE,flush=True)
    sc=fc=sc_checks=fc_checks=None
    if args.backend in {'both','solidcraft'}:
        paths.update(commands=out/'overview.commands.json',solidcraft=cad/'overview.sc',solidcraft_measurements=out/'overview.solidcraft.json')
        write(paths['commands'],{'commands':model.solidcraft_commands(spec,p)})
        cmd=[args.solidcraft_cli,'run',str(paths['commands']),'--save',str(paths['solidcraft']),'--json-out',str(paths['solidcraft_measurements']),'--quiet']
        if args.backend=='both': paths['step']=out/'overview.step'; cmd+=['--out',str(paths['step'])]
        subprocess.run(cmd,check=True,cwd=ROOT,stdout=subprocess.DEVNULL)
        sc=common.measurements(json.loads(paths['solidcraft_measurements'].read_text()),expanded,backend='solidcraft')
        sc_checks=sc_audit(args,spec,p,paths['solidcraft'],out,sc,paths)
    if args.backend in {'both','freecad'}:
        paths.update(freecad=cad/'overview.FCStd',freecad_validation=out/'overview.freecad.json')
        cmd=[args.freecad_python,str(ROOT/'scripts/build_building_stack_freecad.py'),str(paths['case']),str(paths['freecad']),str(paths['freecad_validation'])]
        if args.backend=='both': cmd+=['--compare-step',str(paths['step'])]
        subprocess.run(cmd,check=True,cwd=ROOT,env=common.freecad_environment(args.freecad_python))
        fc_checks=json.loads(paths['freecad_validation'].read_text())
        if fc_checks['source_files_sha256']!=pins or fc_checks['source_sha256']!=digest: raise ValueError('Foreign FreeCAD proof inputs')
        fc=common.measurements(fc_checks,expanded,backend='freecad')
    cross=floor.comparison(sc,fc) if args.backend=='both' else None
    passed=(sc_checks is None or sc_checks['passed']) and (fc_checks is None or fc_checks['passed']) and (cross is None or all(c['passed']for c in cross))
    if not passed: write(out/'failed-checks.json',{'solidcraft':sc_checks,'freecad':fc_checks,'cross':cross}); raise AssertionError('Building native scoped proof failed')
    hashes={key:common.robot_spec.digest(path)for key,path in paths.items()}; renders={}; geometry=sc or fc
    if args.backend in {'both','solidcraft'} and not args.no_render:
        views = ['overview', 'atrium']+(['circulation', 'ground', 'basement'] if contract.get('circulation') else [])+(['roof'] if contract.get('roof') else [])
        views += [room['id'] for room in contract.get('furnishings', {}).get('rooms', [])]
        if contract.get('furnishings'): views.append('Kitchen1008_EasterEgg')
        for view in views:
            if view == 'overview':
                commands=[]; view_geometry=geometry
            elif view == 'atrium':
                hidden=contract['wall_visibility_ids']+contract.get('roof', {}).get('body_ids', [])+contract.get('exterior', {}).get('terrain_body_ids', [])+contract.get('exterior', {}).get('glass_body_ids', [])+contract.get('exterior', {}).get('frame_body_ids', [])
                commands=[{'command':'browser.visibility','params':{'items':hidden,'visible':False}}]; view_geometry=[body for body in geometry if body['body'] not in set(hidden)]
            else:
                furniture_room = next((room for room in contract.get('furnishings', {}).get('rooms', []) if room['id'] == view.removesuffix('_EasterEgg')), None)
                if furniture_room:
                    kept = set(furniture_room['body_ids'])
                    if view.endswith('_EasterEgg'):
                        kept = {name for name in kept if '_Fridge_' in name or '_Penguin' in name}-set(furniture_room['fridge_door_body_ids'])
                elif view == 'circulation':
                    kept=set(contract['circulation']['detail_visibility_ids'])
                elif view == 'basement':
                    basement_level=next(level for level in contract['levels'] if level['id']=='KG')
                    kept=set(basement_level['wall_bodies']+basement_level['floor_bodies'])
                    kept.update(n for key,n in contract.get('exterior', {}).get('door_leaves', {}).items() if key.startswith('KG__'))
                elif view == 'ground':
                    ground_level=next(level for level in contract['levels'] if level['id']=='EG')
                    kept=set(ground_level['wall_bodies']+ground_level['floor_bodies']+contract['circulation']['ground_visibility_ids'])
                    kept.update(n for key,n in contract.get('exterior', {}).get('door_leaves', {}).items() if key.startswith('EG__'))
                    kept.update(n for n in contract.get('exterior', {}).get('glass_body_ids', []) if n.startswith('FoyerGlass_EG_'))
                else:
                    kept=set(contract['roof']['detail_visibility_ids'])
                if not kept or not kept <= {body['body'] for body in geometry}:raise ValueError('Native view requires complete source-bound body visibility roles')
                commands=[{'command':'browser.visibility','params':{'items':[body['body'] for body in geometry if body['body'] not in kept],'visible':False}}]
                view_geometry=[body for body in geometry if body['body'] in kept]
            script=out/(view+'.view.commands.json'); write(script,{'commands':commands}); image=render/(view+'.png'); cam=camera(view_geometry,atrium=view!='overview')
            if view == 'Kitchen1008': cam.update(yaw=2.3, pitch=.55)
            if view == 'Kitchen1008_EasterEgg': cam.update(yaw=3.0, pitch=.12)
            cmd=[args.solidcraft_cli,'snapshot',str(script),'--in',str(paths['solidcraft']),'--out',str(image),'--width','1800','--height','1400','--camera',json.dumps(cam),'--no-grid','--no-axes','--quality','fine']
            subprocess.run(cmd,check=True,cwd=ROOT,stdout=subprocess.DEVNULL)
            renders[view]={'path':relative(image),'sha256':common.robot_spec.digest(image),'pixels':[1800,1400],'camera':cam,
                           'view_commands':commands,'view_script':relative(script),'view_script_sha256':common.robot_spec.digest(script),'command_line':cmd,'visually_reviewed':False}
    common.verify_pins(pins); common.verify_artifacts(paths,hashes)
    report={'format':FORMAT,'source':source_name,'source_sha256':digest,'source_files_sha256':pins,'revision':revision,'passed':passed,
            'exterior':contract.get('exterior'),
            'backends':args.backend,'cross_cad_checked':args.backend=='both','closed_body_count':len(expanded['bodies']),
            'structural_display_body_count':len(expanded['bodies'])-len(contract['marker_body_ids'])-len(contract.get('furnishings', {}).get('body_ids', [])),'marker_body_ids':contract['marker_body_ids'],
            'furnishings':contract.get('furnishings'),
            'coordinate_meaning':NOTICE,'metric_scale_known':False,'assumed_dimensions':contract['assumed_dimensions'],
            'solidcraft_checks':sc_checks,'freecad_checks_passed':None if fc_checks is None else fc_checks['passed'],'body_comparisons':cross,
            'native_corridor_roof_checks_passed':{'solidcraft':None if sc_checks is None else sc_checks.get('native_corridor_roof_checks_passed'),
                                                 'freecad':None if fc_checks is None else fc_checks.get('native_corridor_roof_checks_passed')},
            'maximum_step_xor_presentation_mm3':max(c['xor_mm3']for c in fc_checks['solidcraft_step_xor'])if cross is not None else None,
            'files':{key:relative(path)for key,path in paths.items()},'artifact_sha256':hashes,'renders':renders,'elapsed_s':time.monotonic()-started,
            'global_interference_checked':False,'limitations':['Level-specific referenced plan geometry remains an approximate registered presentation; KG has separately registered geometry with assumed height',
            'XY registration is uncalibrated; old L01 concept dimensions are assumptions, not measurements',
            'Owner-assumed clear heights and illustrative slabs are not a surveyed structural model',
            'Atrium proof covers floor-hole continuity only, excluding wall edges and the illustrative blue marker',
            'No robot, route, physical clearance, load, egress or safety qualification; schematic wall-junction overlaps remain allowed',
            'Circulation witnesses describe connected presentation geometry and scoped apertures, not walking, headroom, elevator operation or structural suitability',
            'Roof, curved glass and guard dimensions are illustrative; no weather sealing, structural, fall-protection or fire-safety qualification',
            'Cutaway/detail views change visibility only; no boolean cutaway is constructed; original photographs are not dependencies']}
    write(out/'build-report.json',report);common.verify_pins(pins);write(ROOT/'cad/building-stack/shared-build-report.json',report)
    print('Building stack passed: '+relative(out/'build-report.json'),flush=True);return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',default=str(model.SOURCE));parser.add_argument('--backend',choices=['both','freecad','solidcraft'],default='both');parser.add_argument('--no-render',action='store_true')
    tool_paths.add_tool_arguments(parser);args=parser.parse_args(argv);needed=common.required_tools(args.backend)
    tools=argparse.Namespace(**{name:getattr(args,name)for name in needed});tool_paths.resolve_tool_arguments(parser,tools,required=needed)
    for name in needed:setattr(args,name,getattr(tools,name))
    return build(args)


if __name__=='__main__': main()
