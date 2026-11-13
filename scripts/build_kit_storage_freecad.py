"""Native S01 geometry and full-footprint witnesses; STEP is optional comparison."""
import argparse
import json
from pathlib import Path
import sys

import FreeCAD as App
import Part

import build_tube_carrier_freecad as native
import build_kit_storage as evidence
import kit_storage_model as model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('case', 'output', 'report'):
        parser.add_argument(name)
    parser.add_argument('--compare-step')
    args = parser.parse_args(argv)
    case = json.loads(Path(args.case).read_text())
    evidence.common.verify_pins(case['source_files_sha256'])
    path = model.ROOT/case['source']
    if model.digest(path) != case['source_sha256']:
        raise ValueError('Storage source changed before native construction')
    model.SOURCE = path
    spec = model.materialize(model.load(path), case['id'])
    p = model.parameters(spec)
    source = model.expanded(spec, p)
    if source['joints']:
        raise ValueError('Storage states must remain static')
    native.model = model
    doc = native.build(model.native_spec(spec, p), p, Path(args.output))
    geometry = native.measurements(doc)
    evidence.common.measurements({'geometry': geometry}, source, backend='freecad')
    shapes = {obj.SourceBody: native.motion.world_shape(obj) for obj in native.objects(doc)}
    interference = native.interference(doc)
    interference['passed'] = not interference['between_components'] and not interference['within_rigid_components']
    probes = []
    for probe in evidence.probe_boxes(spec, p):
        witness = Part.makeBox(*probe['audit_size_mm'], App.Vector(*probe['audit_origin_mm']))
        hits, exact, pruned = [], 0, 0
        for name, shape in shapes.items():
            if not witness.BoundBox.intersect(shape.BoundBox):
                pruned += 1
                continue
            exact += 1
            volume = witness.common(shape).Volume
            if volume > 1e-5:
                hits.append({'body': name, 'volume_mm3': volume})
        probes.append({**probe, 'passed': not hits, 'collisions': hits, 'native_bodies_checked': list(shapes),
                       'exact_intersections': exact, 'bbox_pruned': pruned})
    support = evidence.support_geometry(spec, p, geometry)
    witness = Part.makeBox(*support['witness_size_mm'], App.Vector(*support['witness_origin_mm']))
    support = evidence.support_volumes(support, {name: witness.common(shapes[name]).Volume
                                               for name in (support['carrier_body'], support['support_body'])})
    interfaces = model.check_interface_geometry(spec, p, geometry)
    if not interfaces:
        raise ValueError('Native interface checks required')
    exact = native.step_check(doc, args.compare_step) if args.compare_step else []
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(Path(args.output)))
    doc.recompute()
    reopened = native.measurements(doc)
    evidence.common.measurements({'geometry': reopened}, source, backend='freecad')
    reopen_checks = evidence.common.compare(geometry, reopened)
    App.closeDocument(doc.Name)
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    presentation = persist(args.output, source, geometry)
    evidence.common.verify_pins(case['source_files_sha256'])
    report = {'passed': interference['passed'] and support['passed'] and presentation['passed']
              and all(c['passed'] for c in interfaces+probes+exact+reopen_checks),
              'case': case['id'], 'source_sha256': case['source_sha256'], 'source_files_sha256': case['source_files_sha256'],
              'geometry': geometry, 'interference': interference, 'support': support, 'interfaces': interfaces,
              'access': {'passed': all(c['passed'] for c in probes), 'checks': probes}, 'solidcraft_step_xor': exact,
              'step_comparison_performed': bool(args.compare_step), 'reopened': {'body_comparisons': reopen_checks},
              'presentation': presentation, 'freecad_version': App.Version(),
              'construction': 'Native shared operations; no other-CAD input, optional STEP used only after construction'}
    evidence.write(args.report, report)
    print(json.dumps({'case': case['id'], 'passed': report['passed'], 'body_count': len(geometry),
                      'support': support['passed'], 'access': report['access']['passed']}), flush=True)
    if not report['passed']:
        raise AssertionError('Native storage proof failed: '+args.report)


if __name__ == '__main__':
    import build_kit_storage_freecad as adapter
    adapter.main()
