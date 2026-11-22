"""Build the standalone ice maker in either native CAD from one shared source.

The two cases are explicit appliance variants. Native probes check the modeled
empty bin, envelope, support pads and sampled flap motion; they do not qualify
refrigeration, plumbing, food contact or suitability of a real countertop.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

import ice_maker_model as model
import tool_paths
from build_extraction_kit_station import (
    check_solidcraft_interference, compare, measurements, verify_pins,
)
from build_instrument_concepts import freecad_environment

CASES = ('floor_standing', 'countertop')


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def relative(path):
    return str(Path(path).resolve().relative_to(model.ROOT.resolve()))


def source_snapshot():
    paths = [model.SOURCE, model.SCHEMA, Path(__file__)]
    paths += [model.ROOT/'scripts'/name for name in (
        'ice_maker_model.py', 'assembly_model.py', 'robot_spec.py',
        'tube_carrier_model.py', 'build_tube_carrier_freecad.py',
        'build_neutral_freecad.py', 'robot_cameras.py',
        'build_extraction_kit_station.py', 'build_instrument_concepts.py',
        'freecad/solidcraftbot_freecad.py', 'freecad/persist_station_view.py',
        'freecad/persist_view.py', 'tool_paths.py')]
    return {relative(path): model.digest(path) for path in dict.fromkeys(paths)}


def geometry_checks(spec, p, geometry):
    """Compare measured native bounds with the source envelope and supports."""
    interface = model.interfaces(spec, p)
    low = [min(body['bbox']['min'][i] for body in geometry) for i in range(3)]
    high = [max(body['bbox']['max'][i] for body in geometry) for i in range(3)]
    actual = [high[i]-low[i] for i in range(3)]
    expected = interface['envelope_mm']
    checks = [{'id': 'OverallEnvelope', 'actual_mm': actual, 'expected_mm': expected,
               'passed': all(abs(a-b)<1e-5 for a, b in zip(actual, expected))},
              {'id': 'SupportPlane', 'bottom_z_mm': low[2],
               'passed': abs(low[2])<1e-6 and abs(high[2]-expected[2])<1e-5}]
    by_name = {body['body']: body for body in geometry}
    pads = ['FootPad_'+name for name in ('FL', 'FR', 'RL', 'RR')]
    posts = ['FootPost_'+name for name in ('FL', 'FR', 'RL', 'RR')]
    if ({name for name in by_name if name.startswith('FootPad_')} != set(pads)
            or {name for name in by_name if name.startswith('FootPost_')} != set(posts)):
        raise ValueError('Four named support pads and posts required')
    centres = []
    for name in pads:
        bounds = by_name[name]['bbox']
        centres.append([(bounds['min'][i]+bounds['max'][i])/2 for i in (0, 1)]+[bounds['min'][2]])
    targets = interface['support_centres_mm']
    checks.append({'id': 'FourSupportPads', 'actual_centres_mm': centres,
                   'expected_centres_mm': targets,
                   'passed': len(targets)==4 and all(min(math.dist(c, t) for t in targets)<1e-6 for c in centres)
                             and all(min(math.dist(t, c) for c in centres)<1e-6 for t in targets)})
    return checks


def flap_checks(doc, spec, p, access, opening_origin, opening_size, native):
    """Rotate copied native flap BReps without changing the static document."""
    import FreeCAD as App
    joint = model.flap_interface(spec, p)
    low, high = joint['limits_deg']
    if (low != 0 or not 0 < high <= 90 or len(joint['origin_mm']) != 3
            or len(joint['axis']) != 3 or math.dist(joint['axis'], [0, 0, 0]) < 1e-9):
        raise ValueError('A finite top-hinged flap range from the closed reference is required')
    objects = {obj.SourceBody: obj for obj in native.objects(doc)}
    closed = native.motion.world_shape(objects[joint['body_id']])
    fixed = {name: native.motion.world_shape(obj) for name, obj in objects.items()
             if name != joint['body_id']}
    pivot, axis = App.Vector(*joint['origin_mm']), App.Vector(*joint['axis'])

    def access_overlaps(shape):
        overlaps = []
        for name, body in {**fixed, joint['body_id']: shape}.items():
            if body.BoundBox.intersect(access.BoundBox):
                volume = body.common(access).Volume
                if volume > 1e-5:
                    overlaps.append({'body': name, 'intersection_mm3': volume})
        return overlaps

    samples, witnesses = [], []
    overlaps = access_overlaps(closed)
    witnesses.append({'id': 'ClosedFlapBlocksCentralAccess', 'angle_deg': low,
                      'origin_mm': opening_origin, 'size_mm': opening_size,
                      'overlaps': overlaps,
                      'passed': {row['body'] for row in overlaps} == {joint['body_id']}})
    count = math.ceil((high-low)/5)
    for index in range(count+1):
        angle = low+(high-low)*index/count
        shape = closed.copy()
        shape.rotate(pivot, axis, angle-low)
        collisions, distances = [], []
        for name, body in fixed.items():
            distances.append((shape.distToShape(body)[0], name))
            if shape.BoundBox.intersect(body.BoundBox):
                volume = shape.common(body).Volume
                if volume > 1e-5:
                    collisions.append({'body': name, 'intersection_mm3': volume})
        distance, nearest = min(distances)
        samples.append({'angle_deg': angle,
                        'valid_solid': shape.isValid() and len(shape.Solids) == 1 and shape.Volume > 0,
                        'minimum_distance_mm': distance, 'nearest_body': nearest,
                        'collisions': collisions})
        samples[-1]['passed'] = samples[-1]['valid_solid'] and not collisions
    overlaps = access_overlaps(shape)
    witnesses.append({'id': 'OpenFlapClearsCentralAccess', 'angle_deg': high,
                      'origin_mm': opening_origin, 'size_mm': opening_size,
                      'overlaps': overlaps, 'passed': not overlaps})
    return witnesses, {'id': 'NativeFlapSwing', 'joint': joint,
                       'checked_fixed_body_ids': sorted(fixed), 'samples': samples,
                       'maximum_sample_step_deg': (high-low)/count,
                       'intersection_tolerance_mm3': 1e-5,
                       'passed': all(row['passed'] for row in samples+witnesses),
                       'scope': 'Finite rotations of a copied native flap BRep against all fixed appliance bodies and one central straight-access witness. Saved CAD remains a static closed reference; no native actuation, continuous swept-volume, building-clearance, seal or hardware qualification.'}


def freecad_build(case, output, report, compare_step=None):
    import FreeCAD as App
    import Import
    import Part
    import build_tube_carrier_freecad as native
    spec = model.variant(model.load(), case)
    p = model.parameters(spec)
    source = model.expanded(spec, p)
    native.model = model
    doc = native.build(spec, p, Path(output))
    try:
        geometry = native.measurements(doc)
        measurements({'geometry': geometry}, source, backend='freecad')
        checks = geometry_checks(spec, p, geometry)
        interference = native.interference(doc)
        interface = model.interfaces(spec, p)
        intervals = [interface['bin_'+axis+'_mm'] for axis in ('x', 'y', 'z')]
        sizes = [upper-lower for lower, upper in intervals]
        if any(size<=0 for size in sizes):
            raise ValueError('Positive modeled bin dimensions required')
        inset = min(.25, min(sizes)/20)
        probe = Part.makeBox(*[size-2*inset for size in sizes],
                             App.Vector(*[pair[0]+inset for pair in intervals]))
        overlaps = []
        for obj in native.objects(doc):
            shape = native.motion.world_shape(obj)
            if shape.BoundBox.intersect(probe.BoundBox):
                volume = shape.common(probe).Volume
                if volume>1e-5:
                    overlaps.append({'body': obj.SourceBody, 'intersection_mm3': volume})
        checks.append({'id': 'EmptyBinBelowSill', 'boundary_inset_mm': inset,
                       'probe_volume_l': probe.Volume/1e6, 'overlaps': overlaps,
                       'passed': not overlaps})
        # The same central straight-access witness must be blocked and cleared.
        opening = interface['opening_z_mm']
        half_width = min(40., sizes[0]/4)
        front = -interface['envelope_mm'][1]/2-1
        opening_origin = [(intervals[0][0]+intervals[0][1])/2-half_width, front, opening[0]+8]
        opening_size = [2*half_width, intervals[1][0]+5-front, opening[1]-35-opening_origin[2]]
        if min(opening_size)<=0:
            raise ValueError('Positive central front opening probe required')
        access = Part.makeBox(*opening_size, App.Vector(*opening_origin))
        access_checks, motion_checks = flap_checks(doc, spec, p, access, opening_origin, opening_size, native)
        checks.extend(access_checks)
        bin_volume = math.prod(sizes)/1e6
        checks.append({'id': 'ModeledBinVolume', 'actual_l': bin_volume,
                       'expected_l': interface['bin_below_sill_l'],
                       'passed': abs(bin_volume-interface['bin_below_sill_l'])<1e-8})
        external_step = native.step_check(doc, Path(compare_step)) if compare_step else []
        step_path = Path(report).with_suffix('.step')
        step_doc = App.newDocument('IceMakerStep')
        try:
            parts = []
            for obj in native.objects(doc):
                part = step_doc.addObject('Part::Feature', obj.SourceBody)
                part.Label = obj.SourceBody
                part.Shape = native.motion.world_shape(obj)
                parts.append(part)
            Import.export(parts, str(step_path))
        finally:
            App.closeDocument(step_doc.Name)
        roundtrip = native.step_check(doc, step_path)
        doc.save()
    finally:
        App.closeDocument(doc.Name)
    reopened_doc = App.openDocument(str(Path(output)))
    try:
        reopened_doc.recompute()
        reopened = native.measurements(reopened_doc)
        reopen_checks = compare(geometry, reopened)
    finally:
        App.closeDocument(reopened_doc.Name)
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    presentation = persist(output, source, geometry)
    passed = (all(check['passed'] for check in checks+external_step+roundtrip+reopen_checks)
              and interference['passed'] and not interference['within_rigid_components']
              and motion_checks['passed'] and presentation['passed'])
    result = {'passed': passed, 'geometry': geometry, 'geometric_checks': checks,
              'interference': interference, 'step_comparison': external_step,
              'step_roundtrip': roundtrip, 'freecad_step': relative(step_path),
              'flap_motion': motion_checks,
              'reopened_comparison': reopen_checks, 'presentation': presentation,
              'freecad_version': App.Version(),
              'scope': 'Closed-reference BReps, source envelope, empty modeled bin, four support pads, closed/open central-access witnesses, finite native flap-angle samples and STEP roundtrip; no continuous swept-volume, appliance performance or installation qualification.'}
    write(report, result)
    if not passed:
        raise AssertionError('Native ice-maker checks failed: '+str(report))


def build(args):
    original = model.load()
    pins = source_snapshot()
    stem = 'ice-maker-im01-'+model.digest(model.SOURCE)[:12]
    revision, number = stem, 1
    while any((model.ROOT/folder/revision).exists() for folder in ('cad/generated', 'exports/generated', 'renders')):
        number += 1
        revision = stem+'-r'+str(number)
    cad, out, renders = [model.ROOT/folder/revision for folder in ('cad/generated', 'exports/generated', 'renders')]
    for folder in (cad, out, renders):
        folder.mkdir(parents=True)
    cases = []
    for case in args.variant or CASES:
        verify_pins(pins)
        spec = model.variant(original, case)
        p = model.parameters(spec)
        source = model.expanded(spec, p)
        files, normalized, checks = {}, {}, {}
        if args.backend in ('both', 'solidcraft'):
            files.update(commands=out/(case+'.commands.json'), solidcraft=cad/(case+'.sc'),
                         solidcraft_geometry=out/(case+'.solidcraft.json'), step=out/(case+'.step'))
            write(files['commands'], {'source_sha256': model.digest(model.SOURCE),
                                      'commands': model.solidcraft_commands(spec, p)})
            subprocess.run([args.solidcraft_cli, 'run', str(files['commands']), '--save', str(files['solidcraft']),
                '--out', str(files['step']), '--json-out', str(files['solidcraft_geometry']), '--quiet'],
                check=True, cwd=model.ROOT)
            raw = json.loads(files['solidcraft_geometry'].read_text())
            normalized['solidcraft'] = measurements(raw, source, backend='solidcraft')
            checks['solidcraft_geometry'] = geometry_checks(spec, p, normalized['solidcraft'])
            script = out/(case+'.interference.commands.json')
            files['solidcraft_interference'] = out/(case+'.interference.json')
            write(script, {'commands': [{'command': 'inspect.interference',
                'params': {'bodies': [body['id'] for body in source['bodies']]}}]})
            subprocess.run([args.solidcraft_cli, 'run', str(script), '--in', str(files['solidcraft']),
                '--results', '--quiet', '--json-out', str(files['solidcraft_interference'])],
                check=True, cwd=model.ROOT, stdout=subprocess.DEVNULL)
            checks['solidcraft_interference'] = check_solidcraft_interference(
                json.loads(files['solidcraft_interference'].read_text()), len(source['bodies']))
            if not args.no_render:
                files['preview'] = renders/(case+'.png')
                width, depth, height = model.interfaces(spec, p)['envelope_mm']
                camera = {'target': [0, 0, height/2], 'distance': 2.4*max(width, depth, height),
                          'yaw': -1.0, 'pitch': .35, 'fov': .65}
                subprocess.run([args.solidcraft_cli, 'snapshot', '--in', str(files['solidcraft']),
                    '--out', str(files['preview']), '--width', '1300', '--height', '1300',
                    '--camera', json.dumps(camera), '--no-grid', '--no-axes'],
                    check=True, cwd=model.ROOT, stdout=subprocess.DEVNULL)
        if args.backend in ('both', 'freecad'):
            files.update(freecad=cad/(case+'.FCStd'), freecad_validation=out/(case+'.freecad.json'))
            command = [args.freecad_python, str(Path(__file__).resolve()), '--native-freecad', case,
                       str(files['freecad']), str(files['freecad_validation'])]
            if 'step' in files:
                command.append(str(files['step']))
            subprocess.run(command, check=True, cwd=model.ROOT, env=freecad_environment(args.freecad_python))
            raw = json.loads(files['freecad_validation'].read_text())
            normalized['freecad'] = measurements(raw, source, backend='freecad')
            checks['freecad'] = raw
            files['freecad_step'] = model.ROOT/raw['freecad_step']
        cross = compare(normalized['solidcraft'], normalized['freecad']) if args.backend=='both' else []
        passed = (all(c['passed'] for c in cross)
                  and all(c['passed'] for c in checks.get('solidcraft_geometry', []))
                  and all(checks[key]['passed'] for key in ('solidcraft_interference', 'freecad') if key in checks))
        case_report = {'id': case, 'passed': passed, 'interfaces': model.interfaces(spec, p),
                       'body_count': len(source['bodies']), 'checks': checks, 'body_comparisons': cross,
                       'files': {key: relative(path) for key, path in files.items()},
                       'artifact_sha256': {key: model.digest(path) for key, path in files.items()}}
        write(out/(case+'.build-report.json'), case_report)
        cases.append(case_report)
        if not passed:
            raise AssertionError('Ice-maker validation failed: '+case)
    verify_pins(pins)
    report = {'format': 'solidcraftbot.ice-maker-build/1', 'passed': True, 'revision': revision,
              'source': relative(model.SOURCE), 'source_sha256': model.digest(model.SOURCE),
              'source_files_sha256': pins, 'backends': args.backend,
              'cross_cad_checked': args.backend=='both', 'cases': cases,
              'limitations': original['limitations']}
    write(out/'build-report.json', report)
    write(model.ROOT/'cad/ice-maker/shared-build-report.json', report)
    print('Ice maker passed: '+str(out/'build-report.json'), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['both', 'freecad', 'solidcraft'], default='both')
    parser.add_argument('--variant', action='append', choices=CASES)
    parser.add_argument('--no-render', action='store_true')
    tool_paths.add_tool_arguments(parser)
    args = parser.parse_args(argv)
    required = {'solidcraft_cli', 'freecad_python'} if args.backend=='both' else {
        'freecad_python' if args.backend=='freecad' else 'solidcraft_cli'}
    tool_paths.resolve_tool_arguments(parser, args, required=required)
    return build(args)


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--native-freecad':
        freecad_build(*sys.argv[2:])
    else:
        main()
