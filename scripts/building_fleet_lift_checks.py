"""Fail-closed BF01 lift threshold support preflight, using the current scene.

This deliberately proves only a negative result at a source reference port.
Absence of the particular barrier is not a complete floor, collision, grant,
door-state, capacity or lift-operation certificate. No lift-stage waiver is
implemented here.
"""
import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

import building_fleet_clearance as clearance
import building_fleet_model as model
import building_fleet_navigation as navigation
import building_stack as stack
import walkthrough_world


ROOT = Path(__file__).resolve().parents[1]


def _source_aperture(*, checked_navigation=None):
    """Use the canonical opening, reusing a checked world's validation only.

    A native source-bound world already required complete building validation.
    Its reverified geometry permits reading the same aperture without compiling
    unrelated laboratory furnishings again. Standalone callers still perform
    the original complete source validation.
    """
    source = model.load()
    if checked_navigation is None:
        building = stack.load(model.resolve_pin(source['sources']['building']))
        native_lift = None
    else:
        if checked_navigation.config != source or not isinstance(checked_navigation.mesh, navigation.NativeMesh):
            raise ValueError('Current source-matched native navigation required')
        report, manifest, _ = walkthrough_world.read(checked_navigation.mesh.export, ROOT)
        reference = source['sources']['building']
        if (report['source_files_sha256'].get(reference['path']) != reference['sha256']
                or manifest['elevator'] != checked_navigation.mesh.manifest['elevator']):
            raise ValueError('Native lift must retain the exact current building source and geometry')
        building = model.reference(source, 'building')
        if building.get('format') != stack.FORMAT or building.get('calibration') is not None:
            raise ValueError('Source-bound uncalibrated building stack required')
        stack.circulation.validate_source(building['circulation'])
        native_lift = manifest['elevator']
    parameters = stack.parameters(building)
    plan, _ = stack.templates(building)
    declaration = building['circulation']['elevator']
    opening = next(o for o in plan['openings']
                   if o['id'] == declaration['reference_opening'])
    wall = next(w for w in plan['walls'] if w['id'] == opening['wall'])
    a, b = [plan['vertices'][wall[key]] for key in ('start', 'end')]
    if abs(a[0] - b[0]) > 1e-7:
        raise ValueError('Source lift opening must have the circulation X plane')
    interval = sorted((a[1] + t * (b[1] - a[1])) * parameters['display_scale']
                      for t in opening['interval'])
    if native_lift is not None:
        _check_native_aperture(building, plan, parameters, interval, native_lift)
    return source, interval, declaration['reference_opening']


def _check_native_aperture(building, plan, parameters, interval, native_lift):
    """Bind all source port frames to the already validated native geometry."""
    declaration = building['circulation']['elevator']
    opening = next(row for row in plan['openings'] if row['id'] == declaration['reference_opening'])
    if (opening['wall'] != declaration['sides']['outward']['wall']
            or not all(math.isfinite(v) for v in interval) or interval[0] >= interval[1]
            or native_lift['reference_level'] != declaration['cabin_level']):
        raise ValueError('Native lift disagrees with its source aperture and reference side')
    expected = {(level['id'], side) for level in building['levels'] for side in declaration['sides']}
    ports = native_lift['ports']
    if len(ports) != len(expected) or {(p['level_id'], p['side']) for p in ports} != expected:
        raise ValueError('Every source lift side and level must retain its native port')
    walls = {row['id']: row for row in plan['walls']}
    for port in ports:
        wall_id = declaration['sides'][port['side']]['wall']
        wall = walls[wall_id]
        a, b = [plan['vertices'][wall[key]] for key in ('start', 'end')]
        scale = parameters['display_scale']
        level_index = next(i for i, row in enumerate(building['levels']) if row['id'] == port['level_id'])
        if (wall['kind'] != 'wall' or abs(a[0] - b[0]) > 1e-7
                or not min(a[1], b[1])*scale <= interval[0] < interval[1] <= max(a[1], b[1])*scale
                or port['wall'] != wall_id or port['plane_x_mm'] != a[0]*scale
                or port['height_mm'] != parameters['door_height_mm']
                or port['wall_thickness_mm'] != parameters['display_thickness']
                or port['z_mm'] != (level_index-1)*parameters['floor_pitch_mm']
                or port['cabin_entry_mm'][1] != sum(interval)/2):
            raise ValueError('Native port frame differs from its validated canonical source aperture')


def _verify_export(mesh):
    """Recheck the bytes actually consumed by the supplied checked mesh."""
    if not isinstance(mesh, navigation.NativeMesh):
        raise ValueError('Current source-pinned NativeMesh required')
    if hasattr(mesh, '_runtime_static_cache_token'):
        from building_fleet_runtime_cache import cached_world_report
        cached = cached_world_report(mesh)
        if cached is None:
            raise ValueError('Unverified compact native geometry provenance')
        return cached
    report, _, _ = walkthrough_world.read(mesh.export, ROOT)
    return report


def _contact_strip(mesh, port, aperture, band_height_mm):
    """Inspect an interior witness strip across the complete source aperture.

    All native faces intersecting the contact band are overincluded, rather
    than selecting slab roles or upward horizontal triangles. Therefore an
    empty projection cannot be an artefact of omitting a sill, frame, finish,
    wall top or other potentially supporting source body. Nonempty projection
    is only an inconclusive result, never a positive support certificate.
    """
    lift = mesh.manifest['elevator']
    if (port.get('active') is not True
            or port['level_id'] != lift['reference_level']
            or port['z_mm'] != lift['reference_z_mm']):
        raise ValueError('Active native cabin reference-level port required')
    if port['side'] not in ('inward', 'outward'):
        raise ValueError('Known source lift side required')
    if (len(aperture) != 2 or not all(math.isfinite(v) for v in aperture)
            or aperture[0] >= aperture[1]
            or not math.isfinite(band_height_mm) or band_height_mm <= 0):
        raise ValueError('Finite source aperture and positive contact band required')
    edge = lift['cabin_bounds_mm']['max' if port['side'] == 'inward' else 'min'][0]
    gap = port['plane_x_mm'] - edge
    if (port['side'] == 'inward' and gap <= 0) or (port['side'] == 'outward' and gap >= 0):
        raise ValueError('Native cabin edge must lie inside the source landing plane')
    # These fractions select a reproducible witness within the existing gap;
    # they neither add geometry nor prescribe a vehicle route or clearance.
    xlo, xhi = sorted(edge + gap * fraction for fraction in (1 / 8, 1 / 4))
    ylo, yhi = aperture
    zlo, zhi = port['z_mm'], port['z_mm'] + band_height_mm
    candidates, triangles = [], []
    for group in mesh.scene['groups']:
        bounds = mesh.bounds(group)
        if any(bounds['max'][axis] < lo or bounds['min'][axis] > hi
               for axis, lo, hi in ((0, xlo, xhi), (1, ylo, yhi), (2, zlo, zhi))):
            continue
        projections = []
        for triangle in mesh.triangles(group):
            polygon = navigation.clip_height(triangle, zlo, zhi)
            for axis, limit, greater in ((0, xlo, True), (0, xhi, False),
                                         (1, ylo, True), (1, yhi, False)):
                polygon = clearance._clip(polygon, axis, limit, greater)
            if len(polygon) >= 3 and clearance.signed_area(polygon) != 0:
                projections.append(polygon)
        candidates.append({'body': group['id'], 'role': group['role'],
                           'bounds_mm': bounds,
                           'positive_area_contact_projections': len(projections)})
        for polygon in projections:
            for i in range(1, len(polygon) - 1):
                triangles.append([polygon[0], polygon[i], polygon[i + 1]])
    coverage = clearance.floor_union_covers(
        triangles, [(xlo + xhi) / 2, (ylo + yhi) / 2], 0,
        (xhi - xlo) / 2, (yhi - ylo) / 2)
    return {
        'format': 'solidcraftbot.bf01-lift-support-negative/1',
        'passed': False,
        'status': 'blocked' if not triangles else 'unproven',
        'rejection_proven': not triangles,
        'port_id': port['id'], 'level_id': port['level_id'],
        'z_contact_band_mm': [zlo, zhi], 'opening_y_mm': list(aperture),
        'source_cabin_floor_outer_x_mm': edge,
        'source_port_plane_x_mm': port['plane_x_mm'],
        'missing_strip_mm': {'x': [xlo, xhi], 'y': list(aperture)},
        'strip_width_mm': xhi - xlo,
        'native_groups_examined': len(mesh.scene['groups']),
        'native_candidate_groups': candidates,
        'projected_contact_triangle_count': len(triangles),
        'coverage': coverage,
        'scope': ('Negative support preflight at the native cabin reference level. '
                  'All native faces are overincluded through the complete source '
                  'aperture and floor contact band, using current initial '
                  'articulations. An empty positive-width strip separates cabin '
                  'and landing support under the required whole-footprint floor '
                  'union rule. Nonempty projection remains unproven. Native BRep '
                  'corroboration is separate; no lift-stage qualification is made.')}


def support_barrier(mesh, port_id):
    """Return a pinned rejection witness, or explicitly unproven; never pass."""
    report = _verify_export(mesh)
    source, aperture, opening = _source_aperture()
    matches = [p for p in mesh.manifest['elevator']['ports'] if p['id'] == port_id]
    if len(matches) != 1:
        raise ValueError('Unique source lift port required')
    result = _contact_strip(mesh, matches[0], aperture,
                            source['geometry']['floor_band_start_mm'])
    result.update({
        'source_opening_id': opening,
        'walkthrough_report': str(mesh.world_report_path.relative_to(ROOT)),
        'source_files_sha256': {**report['source_files_sha256'], **model.source_pins(source),
                                **{str((ROOT / 'scripts' / name).relative_to(ROOT)):
                                   model.digest(ROOT / 'scripts' / name)
                                   for name in ('building_fleet_lift_checks.py',
                                                'building_fleet_clearance.py',
                                                'building_fleet_navigation.py')}},
        'artifact_sha256': report['artifact_sha256']})
    return result



@lru_cache(maxsize=4)
def _source_surface_contract(building_sha256, fittings_sha256):
    """Resolve R2 from the existing portable lift construction, never a copy."""
    building = stack.load()
    parameters = stack.parameters(building)
    interface = stack.interfaces(building, parameters)
    elevator = interface['circulation']['elevator']
    fittings = elevator.get('fittings', {})
    thresholds = fittings.get('placements', {}).get('thresholds', [])
    if not thresholds:
        raise ValueError('Source lift threshold geometry is required')
    ports = {row['id']: row for row in elevator['ports'] if row['active']}
    levels = {row['id']: row['z_mm'] for row in interface['levels']}
    reference_level = elevator['cabin_level']
    reference_z = levels[reference_level]
    rows = {}
    offsets = set()
    for threshold in thresholds:
        ident = threshold['port_id']
        if ident not in ports or ident in rows:
            raise ValueError('Exactly one source threshold per active port required')
        port = ports[ident]
        offset = threshold['top_mm'] - port['z_mm']
        if not math.isfinite(offset) or offset < 0:
            raise ValueError('Finite source-derived nonnegative lift top offset required')
        offsets.add(offset)
        side = port['side']
        plan = stack.level_plan(building, port['level_id'])
        landing_areas = [area['id'] for area in plan['areas']
                         if area['id'] != building['circulation']['elevator']['area']
                         and any(edge['wall'] == port['wall'] for edge in area['boundary'])]
        if len(landing_areas) != 1:
            raise ValueError('A unique source-adjacent landing floor is required')
        rows[ident] = {**copy.deepcopy(port),
                      'landing_floor_body_ids': [port['level_id'] + '__Area_' + a for a in landing_areas],
                      'source_threshold': copy.deepcopy(threshold),
                      'height_offset_mm': offset,
                      'source_surface_ids': ['LiftCabinFloorFinish', 'LiftCabinSill_' + side,
                                             threshold['body_id']]}
    if set(rows) != set(ports) or len(offsets) != 1:
        raise ValueError('All active source ports need the same declared lift surface offset')
    return {'format': 'solidcraftbot.bf01-lift-source-surfaces/1',
            'reference_level': reference_level, 'reference_z_mm': reference_z,
            'height_offset_mm': offsets.pop(), 'ports': rows,
            'allowed_roles': {'LiftCabinFloorFinish': 'concept_lift_floor_finish',
                             'LiftCabinSill_': 'concept_lift_cabin_sill',
                             'LiftLandingSill_': 'concept_lift_landing_sill'},
            'source_files_sha256': {'model/building-stack.shared.json': building_sha256,
                                   'scripts/lift_fittings.py': fittings_sha256},
            'derivation': 'circulation.elevator.fittings.placements.thresholds[].top_mm minus matching port.z_mm',
            'qualification': 'Owner synthetic support assumption only; no wheel or chassis qualification'}


def source_surface_contract():
    """Return the current source-derived R2 body identities and top offset."""
    from building_fleet_runtime_cache import cached_surface_contract
    cached = cached_surface_contract()
    if cached is not None:
        return cached
    return copy.deepcopy(_source_surface_contract(
        model.digest(ROOT / 'model/building-stack.shared.json'),
        model.digest(ROOT / 'scripts/lift_fittings.py')))


def active_port(mesh, port_id):
    rows = [p for p in mesh.manifest['elevator']['ports'] if p['id'] == port_id and p['active']]
    if len(rows) != 1:
        raise ValueError('One current active source lift port required')
    return rows[0]


def gate_at(mesh, port_id, timeline, time_s):
    """Require actual compiled cabin FK and fully open source door values."""
    port = active_port(mesh, port_id)
    if type(time_s) not in (int, float) or not math.isfinite(time_s):
        raise ValueError('Finite compiled model time required')
    values = timeline.values(time_s)
    cabin_id = mesh.manifest['elevator']['object_id']
    if abs(values[cabin_id] - port['z_mm']) > 1e-7:
        raise ValueError('Cabin is not at the active port level')
    objects = {obj['id']: obj for obj in mesh.manifest['objects']}
    doors = port.get('door_object_ids', [])
    if not doors or any(ident not in objects or ident not in values for ident in doors):
        raise ValueError('Complete source door values required')
    if any(abs(values[ident] - objects[ident]['states']['open']) > 1e-7 for ident in doors):
        raise ValueError('All cabin and landing doors must be fully open')
    return {'port_id': port_id, 'level_id': port['level_id'], 'cabin_z_mm': values[cabin_id],
            'time_s': time_s, 'fully_open_door_ids': list(doors)}


def posed_mesh(mesh, values):
    """Evaluate the existing native articulation tree at absolute values."""
    result = copy.copy(mesh)
    result._posed_bounds_cache = {}
    result._fleet_band_cache = {}
    result.manifest = copy.deepcopy(mesh.manifest)
    objects = {obj['id']: obj for obj in result.manifest['objects']}
    # Replacing only the reference-relative scalar leaves the shared joint
    # convention unchanged; native vertices themselves are never edited.
    for ident, value in values.items():
        if ident not in objects:
            raise ValueError('Unknown source articulation: ' + ident)
        obj = objects[ident]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Finite absolute articulation value required')
        lo, hi = min(obj['states'].values()), max(obj['states'].values())
        if not lo - 1e-7 <= value <= hi + 1e-7:
            raise ValueError('Articulation value outside source states')
        obj['states']['bf01_compiled_pose'] = value
        obj['initial_state'] = 'bf01_compiled_pose'
    result.transforms = {}
    for obj in objects.values():
        chain = [obj]
        parent = obj.get('parent_object_id')
        while parent:
            chain.append(objects[parent]); parent = objects[parent].get('parent_object_id')
        for body in obj['moving_body_ids']:
            result.transforms[body] = chain
    return result


def fully_open_values(mesh, port_id):
    """Construct a measurement-only source pose, not an execution grant."""
    port = active_port(mesh, port_id)
    objects = {obj['id']: obj for obj in mesh.manifest['objects']}
    result = {mesh.manifest['elevator']['object_id']: port['z_mm']}
    for obj in objects.values():
        if obj.get('mechanism') == 'lift_door':
            result[obj['id']] = obj['states']['open' if obj['id'] in port['door_object_ids'] else 'closed']
    return result


def surface_rows_at(mesh, port_id, timeline, time_s):
    """Collect ordinary slabs and only source-allowed raised lift surfaces.

    The numeric compiled FK/open-door gate is mandatory. This function never
    adds a virtual support rectangle and never treats unrelated raised bodies
    as floors. The shared support engine consumes the actual top triangles.
    """
    gate = gate_at(mesh, port_id, timeline, time_s)
    contract = source_surface_contract()
    entry = contract['ports'].get(port_id)
    if entry is None or entry['z_mm'] != gate['cabin_z_mm']:
        raise ValueError('Port disagrees with the current support construction')
    posed = posed_mesh(mesh, timeline.values(time_s))
    z = entry['z_mm']; raised = z + entry['height_offset_mm']
    allowed = dict(zip(entry['source_surface_ids'],
                       ['concept_lift_floor_finish', 'concept_lift_cabin_sill',
                        'concept_lift_landing_sill']))
    tolerance = mesh.scene.get('maximum_float32_error_mm', 0.) + 1e-8
    rows = []; found = set()
    for group in mesh.scene['groups']:
        identity = group['id']; role = group['role']; bounds = posed.bounds(group)
        if identity in allowed:
            if role != allowed[identity] or abs(bounds['max'][2] - raised) > tolerance:
                raise ValueError('Raised lift body role/top differs from the source: ' + identity)
            expected = raised; found.add(identity)
        elif role == 'concept_storey_slab' and abs(bounds['max'][2] - z) <= tolerance:
            expected = z
        else:
            continue
        triangles = [[p[:2] for p in tri] for tri in posed.triangles(group)
                     if all(abs(p[2] - expected) <= tolerance for p in tri)]
        if not triangles:
            raise ValueError('Source support body has no native horizontal top: ' + identity)
        rows.append({'body_id': identity, 'role': role,
                     'top_z_mm': expected, 'triangles_mm': triangles,
                     'height_exception_applied': identity in allowed})
    if found != set(allowed):
        raise ValueError('A source-required raised lift support body is missing')
    return {'gate': gate, 'surface_rows': rows,
            'source_derived_height_offset_mm': entry['height_offset_mm'],
            'source_contract': contract}



def source_open_timeline(mesh, port_id, source):
    """A source-timed measurement pose sequence, never a fleet-service grant."""
    from check_building_fleet_freecad import timeline_from_manifest
    port = active_port(mesh, port_id)
    config = mesh.manifest['elevator']
    walk = model.reference(source, 'walkthrough')
    duration = walk['elevator']['door_duration']['value']
    schedule = []
    now = 0.
    if port['level_id'] != config['reference_level']:
        schedule.append({'kind':'doors','start_s':now,'end_s':now+duration,
                         'level':config['reference_level'],'target':'closed'})
        now += duration
        travel = 1.875*abs(port['z_mm']-config['reference_z_mm'])/config['speed_mm_s']
        schedule.append({'kind':'travel','start_s':now,'end_s':now+travel,
                         'from_z_mm':config['reference_z_mm'],'to_z_mm':port['z_mm'],
                         'to_level':port['level_id'],'purpose':'standalone_port_geometry_pose'})
        now += travel
        schedule.append({'kind':'doors','start_s':now,'end_s':now+duration,
                         'level':port['level_id'],'target':'open'})
        now += duration
    return timeline_from_manifest(mesh.manifest,schedule), math.ceil(now*1000)/1000


def port_motion_cases(mesh, source, port_id):
    """Compile entry, same-side reverse exit and opposite-side forward exit."""
    import building_fleet_motion as motion
    port = active_port(mesh,port_id)
    timeline,start = source_open_timeline(mesh,port_id,source)
    outside = port['exit_eye_mm'][:2]
    inside = port['cabin_entry_mm'][:2]
    cases=[]
    for name,points,reverse in [('entry',[outside,inside],False),
                                ('same_side_reverse_exit',[inside,outside],True),
                                ('opposite_side_forward_exit',[inside,outside],False)]:
        path=motion.Path(points)
        program=motion.compile_motion(path,source,source['motion']['zone_velocity_mm_s'],
                                      start_s=start,reverse=reverse)
        cases.append({'id':port_id+'.'+name,'port_id':port_id,'level_id':port['level_id'],
                      'kind':name,'reverse':reverse,'points_xy_mm':points,
                      'motion':program,'timeline':timeline})
    return cases


def check_port_curve(mesh, curve, port_id, timeline, source, *, vehicle_id=None,
                     extra_exclusions=(),curve_ref=None):
    """Use the ordinary continuous checker with the narrowly gated lift context."""
    from building_fleet_lift_geometry import PortSupportContext
    port=active_port(mesh,port_id)
    context=PortSupportContext(mesh,source,port_id,timeline,vehicle_id=vehicle_id)
    result=clearance.check_motion(mesh,curve,port['level_id'],source,
                                 extra_exclusions=extra_exclusions,lift_context=context)
    return {**result,'port_id':port_id,'lift_support':context.report(),
            'curve_ref':curve_ref,
            'scope':'Actual exported PVA through real native floor/sill surfaces under R1/R2/R3; whole-floor exclusions retained except the allocated source LiftCore stage. Native BRep motion audit and resource ownership are separate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--walkthrough', required=True, type=Path)
    parser.add_argument('--port', default='LiftPort_EG_inward')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'exports').resolve()):
        raise ValueError('Ignored project exports output required')
    result = support_barrier(navigation.NativeMesh(args.walkthrough), args.port)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in
                      ('status', 'rejection_proven', 'port_id', 'strip_width_mm')}))
    return 2  # Neither a known barrier nor an unproven stage is buildable.


if __name__ == '__main__':
    raise SystemExit(main())
