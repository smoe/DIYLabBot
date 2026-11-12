"""Native synthetic display geometry; no measured building dimensions inferred."""
import argparse
import json
from pathlib import Path
import sys

import FreeCAD as App
import Part

import build_tube_carrier_freecad as native
import build_relative_floorplan as evidence
import relative_floorplan as model


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
        raise ValueError('Derived floorplan changed before native construction')
    model.SOURCE = path
    spec = model.load(path)
    p = model.parameters(spec, case['display_parameters'])
    source = model.expanded(spec, p)
    if source['joints']:
        raise ValueError('Relative display preview must remain static')
    native.model = model
    doc = native.build(model.native_spec(spec, p), p, Path(args.output))
    doc.Controller.addProperty('App::PropertyString', 'CoordinateMeaning', 'Synthetic display')
    doc.Controller.CoordinateMeaning = evidence.UNIT_NOTICE
    doc.Controller.setEditorMode('CoordinateMeaning', 1)
    doc.Controller.addProperty('App::PropertyBool', 'MetricScaleKnown', 'Synthetic display')
    doc.Controller.MetricScaleKnown = False
    doc.Controller.setEditorMode('MetricScaleKnown', 1)
    geometry = native.measurements(doc)
    evidence.common.measurements({'geometry': geometry}, source, backend='freecad')
    shapes = {obj.SourceBody: native.motion.world_shape(obj) for obj in native.objects(doc)}
    checks = []
    for probe in evidence.opening_probes(spec, p):
        points = [App.Vector(x, y, probe['offset_mm']) for x, y in probe['points_mm']]
        wire = Part.makePolygon(points+[points[0]])
        witness = Part.Face(wire).extrude(App.Vector(0, 0, probe['depth_mm']))
        if probe['target_body'] not in shapes or not witness.isValid() or witness.Volume <= 0:
            raise ValueError('Invalid native opening probe/target')
        volume = witness.common(shapes[probe['target_body']]).Volume
        checks.append({'id': probe['id'], 'target_body': probe['target_body'], 'passed': volume <= 1e-5,
                       'overlap_display_mm3': volume, 'probe': probe,
                       'scope': 'Associated display wall cut only; not global building clearance'})
    exact = native.step_check(doc, args.compare_step) if args.compare_step else []
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(Path(args.output)))
    doc.recompute()
    reopened = native.measurements(doc)
    evidence.common.measurements({'geometry': reopened}, source, backend='freecad')
    reopen_checks = evidence.comparison(geometry, reopened)
    App.closeDocument(doc.Name)
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    presentation = persist(args.output, source, geometry)
    evidence.common.verify_pins(case['source_files_sha256'])
    report = {'passed': presentation['passed'] and all(c['passed'] for c in checks+exact+reopen_checks),
              'source_sha256': case['source_sha256'], 'source_files_sha256': case['source_files_sha256'],
              'display_parameters': case['display_parameters'], 'metric_scale_known': False,
              'coordinate_meaning': evidence.UNIT_NOTICE, 'geometry': geometry, 'opening_checks': checks,
              'solidcraft_step_xor': exact, 'step_comparison_performed': bool(args.compare_step),
              'reopened': reopen_checks, 'presentation': presentation, 'freecad_version': App.Version(),
              'interference': {'checked': False, 'junction_overlaps_allowed': True},
              'construction': 'Direct native display prisms and cuts; no imported CAD or photograph input'}
    evidence.write(args.report, report)
    print(json.dumps({'passed': report['passed'], 'body_count': len(geometry), 'opening_probes': len(checks),
                      'metric_scale_known': False, 'native_units': 'synthetic display mm'}), flush=True)
    if not report['passed']:
        raise AssertionError('Native display geometry/opening check failed')


if __name__ == '__main__':
    import build_relative_floorplan_freecad as adapter
    adapter.main()
