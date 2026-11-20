"""Build the syringe concept natively and inspect its geometry and named poses.

This adapter reuses portable primitives and joints.  Its checks do not qualify
gas tightness, manufactured fits, dosing accuracy or a real pipetting motion.
"""
import argparse
import json
import math
from pathlib import Path

import FreeCAD as App
import Part

import build_tube_carrier_freecad as native
import robot_spec
import syringe_pipette as model


def probe_geometry(doc, probes):
    shapes = {obj.SourceBody: native.motion.world_shape(obj) for obj in native.objects(doc)}
    checks = []
    for probe in probes:
        names = probe['body_ids']
        if not names or set(names)-set(shapes):
            raise ValueError('Native probe must reference existing bodies: '+probe['id'])
        line = Part.makeLine(App.Vector(*probe['start_mm']), App.Vector(*probe['end_mm']))
        overlap = sum(shapes[name].common(line).Length for name in names)
        expected = probe['expected']
        if expected not in {'clear', 'blocked'}:
            raise ValueError('Unknown native probe expectation: '+expected)
        checks.append({**probe, 'intersection_length_mm': overlap,
                       'passed': overlap <= 1e-7 if expected == 'clear' else overlap > 1e-7})
    return checks


def build(case_path, output_path, report_path, compare_step=None):
    case = json.loads(Path(case_path).read_text(encoding='utf-8'))
    spec = model.load()
    p = model.parameters(spec, case['overrides'])
    head = case['head']
    source = model.expanded(spec, p, head=head)
    native_spec = model.cad_spec(spec, p)

    class Provider:
        ROOT = model.ROOT
        SOURCE = model.SOURCE
        digest = staticmethod(robot_spec.digest)
        evaluate = staticmethod(robot_spec.evaluate)
        expanded = staticmethod(lambda _spec, _p: source)
        pose = staticmethod(lambda _spec, _p: model.pose(spec, p))
        validate_pose = staticmethod(model.validate_pose)

    native.model = Provider
    doc = native.build(native_spec, p, Path(output_path))
    expressions = model.native_parameter_expressions(spec, prefix='ModelParameters.')
    for name, expression in expressions.items():
        doc.ModelParameters.setExpression(name, expression)
    doc.recompute()
    parameter_checks = []
    for name, expression in expressions.items():
        value = getattr(doc.ModelParameters, name).Value
        parameter_checks.append({'parameter': name, 'native_expression': expression,
                                 'actual_mm': value, 'expected_mm': p[name],
                                 'passed': abs(value-p[name]) < 1e-7})

    baseline = native.measurements(doc)
    baseline_by_name = {row['body']: row for row in baseline}
    baseline_pose = model.pose(spec, p)
    exact = native.step_check(doc, compare_step) if compare_step is not None else None
    cache, pose_checks, named_geometry = {}, [], {}
    named_ids = {sample['id'] for sample in model.build_samples(spec, p)}
    for sample in model.samples(spec, p):
        values = sample.get('joint_values', sample.get('values_mm'))
        native.set_pose(doc, source, values)
        geometry = native.measurements(doc)
        maximum_error = 0
        for row in geometry:
            expected = model.pose_change_point(source, row['component'],
                baseline_by_name[row['body']]['world_center_of_mass_mm'], p, baseline_pose, values)
            maximum_error = max(maximum_error, math.dist(expected, row['world_center_of_mass_mm']))
        probes = model.geometry_probes(spec, p, values, head=head)
        if not probes:
            raise ValueError('No native air-path probes declared for '+sample['id'])
        probe_checks = probe_geometry(doc, probes)
        overlaps = native.interference(doc, cache)
        valid = all(row['valid'] and row['solid_count'] == 1 for row in geometry)
        checks = model.geometry_checks(spec, p, geometry, head=head)
        passed = valid and maximum_error < 1e-7 and all(row['passed'] for row in probe_checks+checks)
        pose_checks.append({**sample, 'maximum_pose_error_mm': maximum_error,
                            'body_geometry_passed': valid, 'geometry_checks': checks,
                            'air_path_probes': probe_checks, 'interference': overlaps,
                            'passed': passed})
        if sample['id'] in named_ids:
            named_geometry[sample['id']] = geometry
    if set(named_geometry) != named_ids:
        raise ValueError('Every named build pose needs a native geometry observation')

    parameter_edits = []
    if case['id'] == 'default':
        for syringe in spec['syringes']:
            radius_name, stroke_name = syringe['radius_parameter'], syringe['stroke_parameter']
            value = 2.6 if syringe['id'] == 'Fine' else 8.0
            changed = {**case['overrides'], radius_name: value}
            pp = model.parameters(spec, changed)
            setattr(doc.ModelParameters, radius_name, value)
            doc.recompute()
            edited_source = model.expanded(spec, pp, head=head)
            start = model.pose(spec, pp, 'park')
            native.set_pose(doc, edited_source, start)
            zero = {row['body']: row for row in native.measurements(doc)}
            endpoint_checks = []
            for displacement in (0, pp[stroke_name]):
                values = {**start, 'Stroke'+syringe['id']: displacement}
                native.set_pose(doc, edited_source, values)
                geometry = native.measurements(doc)
                maximum_error = max(math.dist(row['world_center_of_mass_mm'],
                    model.pose_change_point(edited_source, row['component'],
                        zero[row['body']]['world_center_of_mass_mm'], pp, start, values)) for row in geometry)
                probes = probe_geometry(doc, model.geometry_probes(spec, pp, values, head=head))
                checks = model.geometry_checks(spec, pp, geometry, head=head)
                endpoint_checks.append({'displacement_mm': displacement,
                    'maximum_pose_error_mm': maximum_error, 'air_path_probes': probes,
                    'geometry_checks': checks,
                    'passed': maximum_error < 1e-7 and all(row['passed'] for row in probes+checks)
                              and all(row['valid'] and row['solid_count'] == 1 for row in geometry)})
            stroke = getattr(doc.ModelParameters, stroke_name).Value
            capacity = math.pi*value*value*stroke
            parameter_edits.append({'parameter': radius_name, 'value_mm': value,
                'stroke_parameter': stroke_name, 'native_stroke_mm': stroke,
                'expected_stroke_mm': pp[stroke_name], 'nominal_capacity_ul': syringe['nominal_capacity_ul'],
                'geometric_swept_capacity_ul': capacity, 'endpoint_checks': endpoint_checks,
                'passed': abs(stroke-pp[stroke_name]) < 1e-7
                          and abs(capacity-syringe['nominal_capacity_ul']) < 1e-6
                          and all(row['passed'] for row in endpoint_checks)})
            setattr(doc.ModelParameters, radius_name, p[radius_name])
            doc.recompute()
    native.set_pose(doc, source, baseline_pose)
    for name, value in {
        'ConceptHead': head,
        'DosingAccuracy': 'UNQUALIFIED; no dispensed volume measured',
        'GasTightness': 'UNQUALIFIED; no leak test or Luer conformity proof',
        'Dimensions': 'ASSUMED; no selected or measured syringe/valve/connector article',
        'InterfacesJSON': json.dumps(model.interfaces(spec, p, head=head)),
    }.items():
        doc.Controller.addProperty('App::PropertyString', name, 'Concept qualification')
        setattr(doc.Controller, name, value)
        doc.Controller.setEditorMode(name, 1)
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(output_path))
    doc.recompute()
    reopened = native.measurements(doc)
    reopen_ok = len(reopened) == len(baseline) and all(row['valid'] and row['solid_count'] == 1 for row in reopened)
    App.closeDocument(doc.Name)
    report = {
        'passed': reopen_ok and all(row['valid'] and row['solid_count'] == 1 for row in baseline)
                  and all(row['passed'] for row in parameter_checks+pose_checks+parameter_edits)
                  and (exact is None or all(row['passed'] for row in exact)),
        'scope': 'Native geometry, expressions, joint placements and illustrative air-path probes only',
        'source_sha256': model.digest(model.SOURCE), 'case': case,
        'geometry': baseline, 'named_pose_geometry': named_geometry,
        'native_parameter_checks': parameter_checks, 'motion_samples': pose_checks,
        'native_parameter_edits': parameter_edits,
        'solidcraft_step_xor': exact, 'reopened': {'passed': reopen_ok},
        'collision_free_samples': all(row['interference']['passed'] for row in pose_checks),
        'interference_scope': 'All overlaps reported; fitted seals and manufactured clearance are unqualified',
        'hardware_motion_qualified': False, 'gas_tightness_qualified': False,
        'dosing_accuracy_qualified': False, 'freecad_version': App.Version(),
        'backend': 'Independent expression-driven native primitives and mixed joints; no imported CAD dependency',
    }
    Path(report_path).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'case': case['id'], 'passed': report['passed'], 'bodies': len(baseline),
                      'poses': len(pose_checks), 'collision_free_samples': report['collision_free_samples'],
                      'failed_poses': [row['id'] for row in pose_checks if not row['passed']]}), flush=True)
    if not report['passed']:
        raise AssertionError('Syringe concept native checks failed: '+str(report_path))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--compare-step', type=Path)
    args = parser.parse_args()
    return build(args.case, args.output, args.report, args.compare_step)


if __name__ == '__main__':
    main()
