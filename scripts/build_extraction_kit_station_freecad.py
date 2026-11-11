"""Native static K01 geometry; optional imported STEP is used only for comparison."""
import argparse
import json
from pathlib import Path

import FreeCAD as App
import Part

import build_tube_carrier_freecad as native
import extraction_kit_station as model
import build_extraction_kit_station as evidence


def handle_clearances(doc, spec, p):
    checks = []
    bodies = [(obj.SourceBody, native.motion.world_shape(obj)) for obj in native.objects(doc)]
    for probe in evidence.clearance_probes(spec, p):
        box = Part.makeBox(*probe['audit_size_mm'], App.Vector(*probe['audit_origin_mm']))
        collisions = []
        exact = pruned = 0
        for name, shape in bodies:
            if not box.BoundBox.intersect(shape.BoundBox):
                pruned += 1
                continue
            exact += 1
            volume = box.common(shape).Volume
            if volume > 1e-5:
                collisions.append({'body': name, 'overlap_mm3': volume})
        checks.append({**probe, 'passed': not collisions, 'collisions': collisions,
                       'native_bodies_checked': [name for name, _ in bodies],
                       'exact_intersections': exact, 'bbox_pruned': pruned,
                       'method': 'Native offset Part box versus every model solid'})
    return {'passed': all(check['passed'] for check in checks), 'checks': checks,
            'scope': 'Static source-defined finger and approach envelopes; no real gripper or execution qualification'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case')
    parser.add_argument('output')
    parser.add_argument('report')
    parser.add_argument('--compare-step')
    args = parser.parse_args(argv)
    case = json.loads(Path(args.case).read_text(encoding='utf-8'))
    pins = case['source_files_sha256']
    evidence.verify_pins(pins)
    path = (model.ROOT/case['source']).resolve()
    if model.digest(path) != case['source_sha256']:
        raise ValueError('K01 source changed before FreeCAD construction')
    spec = model.materialize(model.load(path), case['id'])
    p = model.parameters(spec)
    source = model.expanded(spec, p)
    if source['joints']:
        raise ValueError('Static K01 source cannot contain joints')
    native.model = model
    model.SOURCE = path
    doc = native.build(spec, p, Path(args.output))
    geometry = native.measurements(doc)
    evidence.measurements({'geometry': geometry}, source, backend='freecad')
    interfaces = evidence.interface_checks(spec, p, geometry)
    clearances = handle_clearances(doc, spec, p)
    interference = native.interference(doc)
    # Unlike moving mechanisms, this concept has no permitted rigid overlaps.
    interference['passed'] = not interference['between_components'] and not interference['within_rigid_components']
    exact = native.step_check(doc, args.compare_step) if args.compare_step else []
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(Path(args.output)))
    doc.recompute()
    reopened = native.measurements(doc)
    evidence.measurements({'geometry': reopened}, source, backend='freecad')
    reopen_checks = evidence.compare(geometry, reopened)
    import sys
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    App.closeDocument(doc.Name)
    presentation = persist(args.output, source, geometry)
    evidence.verify_pins(pins)
    report = {'passed': interference['passed'] and clearances['passed'] and presentation['passed']
              and all(c['passed'] for c in interfaces+exact+reopen_checks),
              'source_sha256': case['source_sha256'], 'source_files_sha256': pins, 'case': case['id'],
              'geometry': geometry, 'interfaces': interfaces, 'interference': interference,
              'handle_approach_clearances': clearances,
              'solidcraft_step_xor': exact, 'step_comparison_performed': bool(args.compare_step),
              'reopened': {'passed': all(c['passed'] for c in reopen_checks), 'body_comparisons': reopen_checks},
              'freecad_presentation': presentation, 'freecad_version': App.Version(),
              'backend': 'Native shared-operation Part primitives and booleans; no imported CAD construction input'}
    evidence.write(args.report, report)
    print(json.dumps({'case': case['id'], 'passed': report['passed'], 'body_count': len(geometry),
                      'interferences': interference['between_components']+interference['within_rigid_components']}), flush=True)
    if not report['passed']:
        raise AssertionError('K01 FreeCAD validation failed: '+args.report)


if __name__ == '__main__':
    import build_extraction_kit_station_freecad as adapter
    adapter.main()
