"""Measure all source lift thresholds from independently loaded native BReps.

This is a geometry/support measurement, not a wheel, lift-operation, trajectory
or person-safety qualification. The ordinary BF01 support checker remains the
only policy evaluator; this adapter supplies independent native measurements.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import time

import building_fleet_model as model
import building_fleet_lift_checks as lift
import check_building_fleet_freecad as native_check
import export_building_walkthrough_freecad as native

ROOT = Path(__file__).resolve().parents[1]


def _face_top(shape, expected_z, tolerance=1e-7):
    """Extract only actual horizontal upward native faces at the source top."""
    rows = []
    for face in shape.Faces:
        bounds = face.BoundBox
        if abs(bounds.ZMin - expected_z) > tolerance or abs(bounds.ZMax - expected_z) > tolerance:
            continue
        normal = face.normalAt(0, 0)
        if normal.z <= 0 or abs(normal.x) > tolerance or abs(normal.y) > tolerance:
            continue
        rows.append(face)
    if not rows:
        raise ValueError('No horizontal native source top at ' + str(expected_z))
    return rows


def _bounds(shape):
    bb = shape.BoundBox
    return {'min': [bb.XMin, bb.YMin, bb.ZMin], 'max': [bb.XMax, bb.YMax, bb.ZMax]}


def _flat(face):
    result = face.copy()
    result.translate(__import__('FreeCAD').Vector(0, 0, -face.BoundBox.ZMin))
    return result


def _rectangle_face(Part, App, xmin, xmax, ymin, ymax, z=0):
    return Part.Face(Part.makePolygon([App.Vector(xmin, ymin, z), App.Vector(xmax, ymin, z),
                                     App.Vector(xmax, ymax, z), App.Vector(xmin, ymax, z),
                                     App.Vector(xmin, ymin, z)]))


def audit(walkthrough_report, output):
    started = time.monotonic()
    import FreeCAD as App
    import Part
    sys.path.insert(0, str(ROOT / 'scripts/freecad'))
    import solidcraftbot_freecad as geometry
    walkthrough_report = native.project_path(walkthrough_report)
    walk, reports, manifest, _ = native_check.checked_walkthrough(walkthrough_report)
    source = model.load()
    initial_pins = {**model.source_pins(source),
                    'scripts/check_building_fleet_freecad.py':native.digest(ROOT/'scripts/check_building_fleet_freecad.py'),
                    'scripts/export_building_walkthrough_freecad.py':native.digest(ROOT/'scripts/export_building_walkthrough_freecad.py'),
                    'scripts/building_fleet_lift_checks.py':native.digest(ROOT/'scripts/building_fleet_lift_checks.py'),
                    str(Path(__file__).relative_to(ROOT)):native.digest(__file__)}
    contract = lift.source_surface_contract()
    maximum_gap = model.support_settings(source)['gap']['maximum']
    building = reports['building']
    doc = App.openDocument(str(native.project_path(building['files']['freecad'])))
    objects = {obj['id']: obj for obj in manifest['objects']}
    chains = {}
    for obj in objects.values():
        chain = [obj]
        parent = obj.get('parent_object_id')
        while parent:
            chain.append(objects[parent]); parent = objects[parent].get('parent_object_id')
        for body in obj['moving_body_ids']:
            chains[body] = chain
    world = {}; all_native_ids = []
    allowed_support_ids = {identity for row in contract['ports'].values() for identity in row['source_surface_ids']}
    allowed_support_ids.update(identity for row in contract['ports'].values() for identity in row['landing_floor_body_ids'])
    try:
        for obj in geometry.features(doc):
            identity = str(obj.SourceBody)
            all_native_ids.append(identity)
            role = str(getattr(obj, 'ModelRole', 'native_geometry'))
            if identity not in allowed_support_ids:
                continue
            shape = geometry.world_shape(obj)
            if shape.isNull() or not shape.isValid() or not shape.Solids:
                raise ValueError('Invalid native lift audit body: ' + identity)
            world[identity] = {'shape': shape, 'role': role}
    finally:
        App.closeDocument(doc.Name)
    print(json.dumps({'stage':'native_support_bodies_loaded','all_native_bodies':len(all_native_ids),'support_bodies':len(world)}),flush=True)
    scene = type('ManifestOnly', (), {'manifest': manifest})()
    results = []
    for port in manifest['elevator']['ports']:
        if not port['active']:
            continue
        values = lift.fully_open_values(scene, port['id'])
        posed = {}
        for ident, row in world.items():
            chain = chains.get(ident, [])
            shape = row['shape'].copy() if chain else row['shape']
            for obj in chain:
                value = values.get(obj['id'], obj['states'][obj.get('initial_state', obj['reference_state'])])
                shape.Placement = native_check.object_transform(obj, value, App).multiply(shape.Placement)
            posed[ident] = dict(row, shape=shape)
        entry = contract['ports'][port['id']]
        expected_top = port['z_mm'] + entry['height_offset_mm']
        cabin_id = 'LiftCabinSill_' + port['side']
        landing_id = entry['source_threshold']['body_id']
        finish_id = 'LiftCabinFloorFinish'
        source_ids = [finish_id, cabin_id, landing_id]
        top_faces = {}
        for ident in source_ids:
            if ident not in posed:
                raise ValueError('Missing native R2 body: ' + ident)
            top_faces[ident] = _face_top(posed[ident]['shape'], expected_top)
        cb, lb = _bounds(posed[cabin_id]['shape']), _bounds(posed[landing_id]['shape'])
        outward = port['side'] == 'outward'
        edge = cb['min'][0] if outward else cb['max'][0]
        landing_edge = lb['max'][0] if outward else lb['min'][0]
        gap_lo, gap_hi = sorted([edge, landing_edge])
        gap = gap_hi-gap_lo
        lo, hi = entry['source_threshold']['opening_y_mm']
        ycover = {'cabin': [cb['min'][1], cb['max'][1]],
                  'landing': [lb['min'][1], lb['max'][1]]}
        if any(a > lo+1e-7 or b < hi-1e-7 for a, b in ycover.values()):
            raise ValueError('Threshold native faces do not span complete source aperture')
        # Both source sills are rectangular native solids. Matching top-face
        # area to their complete XY boxes proves the measured gap is constant
        # across the full aperture, not only at the centreline.
        face_checks = []
        for ident in (cabin_id, landing_id):
            shape = posed[ident]['shape']; bb = _bounds(shape)
            expected_area = (bb['max'][0]-bb['min'][0])*(bb['max'][1]-bb['min'][1])
            actual_area = sum(face.Area for face in top_faces[ident])
            if abs(actual_area-expected_area) > 1e-7*max(1, expected_area):
                raise ValueError('Native sill top is not the complete source rectangle')
            face_checks.append({'body': ident, 'expected_rectangle_area_mm2': expected_area,
                                'actual_top_face_area_mm2': actual_area})
        exact_gap = min(a.distToShape(b)[0] for a in top_faces[cabin_id] for b in top_faces[landing_id])
        if abs(exact_gap-gap) > 1e-7:
            raise ValueError('Native face distance and full-width rectangular gap differ')
        # Inspect the entire threshold strip for any further dark opening.
        # Only role-allowed faces at the exact source heights join the ordinary
        # storey slabs. Other bodies at the same raised top are not admitted.
        floor_faces = []
        floor_ids = []
        for ident, row in posed.items():
            if ident not in entry['landing_floor_body_ids'] or row['role'] != 'concept_storey_slab':
                continue
            bb = row['shape'].BoundBox
            if abs(bb.ZMax-port['z_mm']) > 1e-7:
                continue
            if bb.XMax < min(cb['min'][0], lb['min'][0]) or bb.XMin > max(cb['max'][0], lb['max'][0]):
                continue
            if bb.YMax < lo or bb.YMin > hi:
                continue
            floor_faces.extend(_face_top(row['shape'], port['z_mm']))
            floor_ids.append(ident)
        if not floor_faces:
            raise ValueError('No native adjacent storey floor at active port')
        floor_union = _flat(floor_faces[0])
        for face in floor_faces[1:]:floor_union = floor_union.fuse(_flat(face))
        landing_flat = _flat(top_faces[landing_id][0])
        for face in top_faces[landing_id][1:]:landing_flat = landing_flat.fuse(_flat(face))
        outer_end = lb['min'][0] if outward else lb['max'][0]
        ox0,ox1 = sorted([port['plane_x_mm'],outer_end])
        overlap_query = _rectangle_face(Part,App,ox0,ox1,lo,hi)
        ordinary_overlap = floor_union.common(landing_flat).common(overlap_query).Area
        if abs(ordinary_overlap-overlap_query.Area) > 1e-7*max(1,overlap_query.Area):
            raise ValueError('Native landing sill does not join the complete source floor aperture')
        projected = [_flat(face) for faces in top_faces.values() for face in faces] + [_flat(face) for face in floor_faces]
        flat_union = projected[0]
        for face in projected[1:]:
            flat_union = flat_union.fuse(face)
        qlo, qhi = min(cb['min'][0],lb['min'][0]), max(cb['max'][0],lb['max'][0])
        query = _rectangle_face(Part,App,qlo,qhi,lo,hi)
        gap_face = _rectangle_face(Part,App,gap_lo,gap_hi,lo,hi)
        covered_area = flat_union.common(query).Area
        expected_missing = gap_face.Area
        missing_area = query.Area-covered_area
        if abs(missing_area-expected_missing) > 1e-7*max(1, query.Area):
            raise ValueError('Native threshold has an additional unsupported region: '+port['id'])
        rows = []
        for ident in source_ids:
            bb=_bounds(posed[ident]['shape'])
            rows.append({'body_id':ident,'role':posed[ident]['role'],'bounds_mm':bb,
                         'top_relative_to_floor_mm':bb['max'][2]-port['z_mm']})
        # Exact source articulation closure after applying each cabin FK pose.
        cabin_box = _bounds(posed[finish_id]['shape'])
        print(json.dumps({'stage':'port_measured','port_id':port['id'],'gap_mm':gap,'top_offset_mm':entry['height_offset_mm']}),flush=True)
        results.append({'port_id':port['id'],'level_id':port['level_id'],'side':port['side'],
                        'cabin_absolute_z_mm':values[manifest['elevator']['object_id']],
                        'source_derived_top_offset_mm':entry['height_offset_mm'],
                        'source_opening_y_mm':[lo,hi],'gap_bounds_mm':{'x':[gap_lo,gap_hi],'y':[lo,hi],'z':[expected_top,expected_top]},
                        'gap_mm':gap,'exact_native_face_gap_mm':exact_gap,
                        'sill_top_faces':face_checks,'surface_bodies':rows,
                        'adjacent_storey_floor_bodies':floor_ids,
                        'projected_threshold_area_mm2':query.Area,'raw_missing_area_mm2':missing_area,
                        'expected_only_gap_area_mm2':expected_missing,
                        'landing_floor_overlap_area_mm2':ordinary_overlap,
                        'source_wall_overlap_area_mm2':overlap_query.Area,
                        'whole_aperture_measured':True,'additional_gap_found':False,
                        'measurement_passed':gap<=maximum_gap,
                        'source_maximum_gap_mm':maximum_gap,
                        'door_values':{ident:values[ident]for ident in port['door_object_ids']},
                        'cabin_finish_posed_bounds_mm':cabin_box})
    native.verify_pins(walk['source_files_sha256'])
    native.verify_pins(initial_pins)
    pins={**walk['source_files_sha256'],**contract['source_files_sha256'],**initial_pins,
          str(Path(__file__).relative_to(ROOT)):native.digest(__file__),
          'scripts/building_fleet_lift_checks.py':native.digest(ROOT/'scripts/building_fleet_lift_checks.py')}
    result={'format':'solidcraftbot.bf01-native-lift-surface-measurement/1',
            'passed':len(results)==5 and all(row['measurement_passed']for row in results),
            'ports':results,'native_building_body_count':len(all_native_ids),
            'native_support_body_count':len(world),
            'walkthrough_report':{'path':str(walkthrough_report.relative_to(ROOT)),'sha256':native.digest(walkthrough_report)},
            'building_native_report':{'path':walk['native_builds']['building']['report'],'sha256':walk['native_builds']['building']['report_sha256']},
            'source_files_sha256':pins,'building_artifacts':{key:{'path':name,'sha256':building['artifact_sha256'][key]}for key,name in building['files'].items()},
            'elapsed_s':time.monotonic()-started,
            'scope':'Exact native BRep horizontal-face and full-aperture gap measurements of all admissible support bodies (other native building IDs inventoried, not claimed collision-checked) at all five absolute source cabin FK positions; fully open source door poses. No trajectory, disk-closing, wheel, hardware or safety qualification.'}
    output=native.project_path(output)
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed':result['passed'],'ports':[{k:r[k]for k in('port_id','gap_mm','source_derived_top_offset_mm')}for r in results],'seconds':result['elapsed_s'],'output':str(output)}))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--walkthrough-report',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();result=audit(args.walkthrough_report,args.output)
    raise SystemExit(0 if result['passed'] else 2)


if __name__=='__main__':main()
