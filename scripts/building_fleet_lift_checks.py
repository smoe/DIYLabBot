"""Fail-closed BF01 lift threshold support preflight, using the current scene.

This deliberately proves only a negative result at a source reference port.
Absence of the particular barrier is not a complete floor, collision, grant,
door-state, capacity or lift-operation certificate. No lift-stage waiver is
implemented here.
"""
import argparse
import json
import math
from pathlib import Path

import building_fleet_clearance as clearance
import building_fleet_model as model
import building_fleet_navigation as navigation
import building_stack as stack


ROOT = Path(__file__).resolve().parents[1]


def _source_aperture():
    """Use precisely the canonical opening and scale used by circulation."""
    source = model.load()
    building = stack.load(model.resolve_pin(source['sources']['building']))
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
    return source, interval, declaration['reference_opening']


def _verify_export(mesh):
    """Recheck the bytes actually consumed by the supplied checked mesh."""
    if not isinstance(mesh, navigation.NativeMesh):
        raise ValueError('Current source-pinned NativeMesh required')
    export = Path(mesh.export).resolve()
    if not export.is_relative_to(ROOT):
        raise ValueError('Project-local checked walkthrough required')
    report = model.read_json(export / 'build-report.json')
    if (report.get('format') != 'solidcraftbot.building-walkthrough-build/1'
            or report.get('passed') is not True
            or not report.get('source_files_sha256')
            or set(report.get('files', {})) != {'html', 'native_mesh', 'manifest'}):
        raise ValueError('Successful checked walkthrough report required')
    for name, digest in report['source_files_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or model.digest(path) != digest:
            raise ValueError('Stale walkthrough source: ' + name)
    for key, name in report['files'].items():
        path = (export / Path(name).name).resolve()
        if (not path.is_relative_to(export) or not path.is_file()
                or model.digest(path) != report['artifact_sha256'][key]):
            raise ValueError('Changed consumed walkthrough artifact: ' + name)
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
        'walkthrough_report': str((Path(mesh.export) / 'build-report.json').relative_to(ROOT)),
        'source_files_sha256': {**report['source_files_sha256'], **model.source_pins(source),
                                **{str((ROOT / 'scripts' / name).relative_to(ROOT)):
                                   model.digest(ROOT / 'scripts' / name)
                                   for name in ('building_fleet_lift_checks.py',
                                                'building_fleet_clearance.py',
                                                'building_fleet_navigation.py')}},
        'artifact_sha256': report['artifact_sha256']})
    return result


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
