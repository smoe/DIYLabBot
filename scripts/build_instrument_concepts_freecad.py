"""Native FreeCAD instrument geometry and independent sampled hinge checks."""
import json
import math
from pathlib import Path
import sys

import FreeCAD as App
import Part

import build_tube_carrier_freecad as native
import instrument_concept as model


def main(source_path, output_path, case_path, report_path, step_path):
    source_path = Path(source_path)
    spec = model.load(source_path)
    case = json.loads(Path(case_path).read_text(encoding='utf-8'))
    p = model.parameters(spec, case['overrides'])
    # Reuse the existing native primitive/sketch/boolean/hinge implementation.
    native.model = model
    model.SOURCE = source_path
    doc = native.build(spec, p, Path(output_path))
    geometry = native.measurements(doc)
    step_checks = native.step_check(doc, step_path)
    baseline_angle = model.pose(spec, p)['Hinge']
    baseline = {b['body']: b for b in geometry}
    samples = []
    rigid_cache = {}
    for sample in model.samples(spec, p):
        angle = sample['joint_values']['Hinge']
        native.set_pose(doc, model.expanded(spec, p), sample['joint_values'])
        current = native.measurements(doc)
        errors = []
        for body in current:
            old = baseline[body['body']]['world_center_of_mass_mm']
            # Transform the saved open pose back to its common-source zero frame.
            zero = model.transform(spec, p, body['component'], old, -baseline_angle)
            expected = model.transform(spec, p, body['component'], zero, angle)
            errors.append(math.dist(body['world_center_of_mass_mm'], expected))
        collisions = native.interference(doc, rigid_cache)
        samples.append({**sample, 'max_center_error_mm': max(errors), **collisions,
                        'passed': max(errors) < 1e-7 and collisions['passed']})
    native.set_pose(doc, model.expanded(spec, p), model.pose(spec, p, 'closed'))
    closed_geometry = native.measurements(doc)
    native.set_pose(doc, model.expanded(spec, p), model.pose(spec, p))
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(output_path))
    doc.recompute()
    reopened = native.measurements(doc)
    reopened_ok = (len(reopened) == len(geometry)
                   and all(b['valid'] and b['solid_count'] == 1 for b in reopened))
    # The access target must be an actual face/axis, not just a declared frame.
    by_name = {b['body']: b for b in geometry}
    if spec['family'] == 'nanodrop-concept':
        surface = by_name['LowerOpticalFace']
        drop = by_name['SampleDrop']
        interfaces = [
            {'id': 'flat_lower_surface', 'passed': abs(surface['bbox']['max'][2] - p['sample_z']) < 1e-7},
            {'id': 'drop_on_surface', 'passed': abs(drop['bbox']['min'][2] - p['sample_z']) < 1e-7},
            {'id': 'drop_volume', 'volume_ul': drop['volume_mm3'],
             'passed': abs(drop['volume_mm3'] - spec['sample_reference']['volume_ul']) < 1e-6}]
    else:
        collar = next(o for o in native.objects(doc) if o.SourceBody == 'ChamberCollar')
        axis = Part.makeLine(App.Vector(p['sample_x'], p['sample_y'], p['sample_z']-10),
                             App.Vector(p['sample_x'], p['sample_y'], p['sample_z']+1))
        interfaces = [{'id': 'open_chamber_axis',
                       'passed': native.motion.world_shape(collar).common(axis).Length < 1e-7}]
    report = {'passed': (all(b['valid'] and b['solid_count'] == 1 for b in geometry)
                         and all(c['passed'] for c in step_checks + samples + interfaces)
                         and reopened_ok),
              'source_sha256': model.digest(source_path), 'geometry': geometry,
              'closed_geometry': closed_geometry,
              'solidcraft_step_xor': step_checks, 'motion_samples': samples,
              'interfaces': interfaces, 'reopened': {'passed': reopened_ok},
              'freecad_version': App.Version(),
              'backend': 'Native expression-driven Part primitives, sketches, booleans and hinge placement; STEP used only for comparison'}
    Path(report_path).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    App.closeDocument(doc.Name)
    print(json.dumps({'passed': report['passed'], 'body_count': len(geometry),
                      'failed_poses': [s['id'] for s in samples if not s['passed']],
                      'interference_pairs': sorted({(c['a'], c['b']) for s in samples
                                                     for c in s['between_components']})}), flush=True)
    if not report['passed']:
        raise AssertionError('Instrument geometry validation failed: ' + report_path)


if __name__ == '__main__':
    # FreeCAD initializes __main__; keep the adapter's globals in its module.
    import build_instrument_concepts_freecad as adapter
    adapter.main(*sys.argv[1:])
