"""Generate native H01 models, compare kernels, and validate sampled handoff poses."""
from pathlib import Path
import argparse
import ast
import json
import math
import shutil
import subprocess
import sys
import time
import tube_carrier_model as model


def write(path, value): Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def compare(actual, expected):
    refs = {b['body']: b for b in expected}
    if set(refs) != {b['name'] for b in actual['bodies']}: raise AssertionError('Body names/count mismatch')
    result = []
    for body in actual['bodies']:
        ref = refs[body['name']]
        v = abs(body['volume_mm3'] - ref['volume_mm3']) / ref['volume_mm3']
        com = math.dist(body['center_of_mass'], ref['world_center_of_mass_mm'])
        bb = max(abs(a-b) for key in ['min', 'max'] for a, b in zip(body['bbox'][key], ref['bbox'][key]))
        result.append({'body': body['name'], 'relative_volume_error': v, 'com_error_mm': com, 'bbox_error_mm': bb,
            'passed': body['closed'] and v < 0.001 and com < 0.01 and bb < 0.01})
    return result


def analytic_checks(actual, spec, p):
    if hasattr(model, 'analytic_checks'): return model.analytic_checks(actual, spec, p)
    bodies = {b['name']: b for b in actual['bodies']}; result = []
    for variant in spec['variants']:
        tag = variant['id']; radius = p['tube_radius']; z = p['tube_bottom_z']; top = p['collar_z']
        if variant['bottom'] == 'conical':
            height = p['cone_join_z'] - z
            lower = math.pi * height * (0.8**2 + 0.8*radius + radius**2) / 3
            upper = math.pi * radius**2 * (top - p['cone_join_z'])
        else:
            points = [(radius*math.sin(math.radians(a)), z+radius*(1-math.cos(math.radians(a)))) for a in spec['rounded_profile_angles_deg']]
            lower = sum(math.pi*(b[1]-a[1])*(a[0]**2+a[0]*b[0]+b[0]**2)/3 for a, b in zip(points, points[1:]))
            upper = math.pi * radius**2 * (top - z - radius)
        tube = lower + upper + math.pi * p['collar_radius']**2 * 2 - math.pi * (radius-0.7)**2 * (top+2-p['cone_join_z'])
        for name, expected in [(tag+'_DockBase', 44*50*6), (tag+'_DockFloor', 30*36*2-3.6*36*1.6),
                               (tag+'_RailL', 4*22*6+1.9*22*2.5), (tag+'_ReferenceTube', tube)]:
            actual_volume = bodies[name]['volume_mm3']; error = abs(actual_volume-expected)/expected
            result.append({'body': name, 'expected_volume_mm3': expected, 'actual_volume_mm3': actual_volume,
                'relative_error': error, 'passed': error < 0.001})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad-python', default=str(Path.home()/'AppData/Local/Programs/FreeCAD 27.1/bin/python.exe'))
    parser.add_argument('--solidcraft-cli', default=shutil.which('solidcraft-cli') or 'solidcraft-cli')
    args = parser.parse_args(); spec = model.load(); started = time.monotonic()
    family = spec.get('family', 'tube-carrier-h01')
    stem = family+'-' + model.digest(model.SOURCE)[:12]; revision = stem; counter = 1
    while (model.ROOT/'cad/generated'/revision).exists():
        counter += 1; revision = stem + '-r' + str(counter)
    cad = model.ROOT/'cad/generated'/revision; out = model.ROOT/'exports/generated'/revision
    cad.mkdir(parents=True); out.mkdir(parents=True); (model.ROOT/'cad'/family).mkdir(exist_ok=True)
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    reports = []; native = []
    cases = [('default', {}),
        ('lower_bounds', {k: d['range'][0] for k, d in spec['parameters'].items() if d['range'][0] != d['range'][1] and not any(isinstance(n, ast.Name) for n in ast.walk(ast.parse(str(d['expression']), mode='eval')))}),
        ('upper_bounds', {k: d['range'][1] for k, d in spec['parameters'].items() if d['range'][0] != d['range'][1] and not any(isinstance(n, ast.Name) for n in ast.walk(ast.parse(str(d['expression']), mode='eval')))})]
    for name, overrides in cases:
        print('Carrier case: ' + name, flush=True); p = model.parameters(spec, overrides)
        prefix = cad/(spec['id'] if name == 'default' else spec['id']+'_'+name)
        sc = prefix.with_suffix('.sc'); fc = prefix.with_suffix('.FCStd'); step = out/(name+'.step')
        script = out/(name+'.commands.json'); casefile = out/(name+'.case.json')
        scmeasured = out/(name+'.solidcraft.json'); fcreport = out/(name+'.freecad.json')
        write(script, {'source_sha256': model.digest(model.SOURCE), 'commands': model.solidcraft_commands(spec, p)})
        write(casefile, {'id': name, 'overrides': overrides})
        subprocess.run([args.solidcraft_cli, 'run', str(script), '--save', str(sc), '--out', str(step), '--json-out', str(scmeasured), '--quiet'], check=True, cwd=model.ROOT)
        subprocess.run([args.freecad_python, str(model.ROOT/spec.get('freecad_adapter', 'scripts/build_tube_carrier_freecad.py')), str(fc), str(casefile), str(fcreport), str(step)], check=True, cwd=model.ROOT)
        scm = json.loads(scmeasured.read_text(encoding='utf-8')); fcm = json.loads(fcreport.read_text(encoding='utf-8'))
        cross = compare(scm, fcm['geometry']); analytic = analytic_checks(scm, spec, p)
        presentation = persist(fc, model.expanded(spec, p), fcm['geometry'])
        item = {'id': name, 'overrides': overrides, 'passed': fcm['passed'] and all(c['passed'] for c in cross+analytic) and presentation['passed'],
            'body_comparisons': cross, 'analytic_volume_checks': analytic, 'maximum_step_xor_mm3': max(c['xor_mm3'] for c in fcm['solidcraft_step_xor']),
            'motion_samples': len(fcm['motion_samples']), 'freecad_native_parameter_edits': [{k: v for k, v in edit.items() if k != 'geometry'} for edit in fcm['native_parameter_edits']],
            'freecad_presentation': presentation,
            'files': {k: str(v.relative_to(model.ROOT)).replace('\\', '/') for k, v in {'solidcraft': sc, 'freecad': fc, 'step': step, 'solidcraft_measurements': scmeasured, 'freecad_validation': fcreport, 'commands': script}.items()},
            'artifact_sha256': {'solidcraft': model.digest(sc), 'freecad': model.digest(fc), 'step': model.digest(step)}}
        reports.append(item); write(out/'cases-progress.json', reports)
        if not item['passed']: raise AssertionError(spec['id']+' cross-CAD check failed: ' + name)
        if name == 'default':
            for edit in fcm['native_parameter_edits']:
                parameter = edit['parameter']; value = edit['value_mm']
                editfile = out/f'edit-{parameter}-{value}.commands.json'; measured = out/f'edit-{parameter}-{value}.solidcraft.json'
                # Re-evaluate the source-driven display poses after travel limits change.
                # Other native edits preserve the default numeric slider values.
                commands = [{'command': 'parameters.change', 'params': {'name': parameter, 'expression': str(value)+' mm'}}]
                for joint, position in edit['effective_pose_mm'].items():
                    commands.append({'command': 'joint.drive', 'params': {'joint': joint, 'value': position, 'quiet': True}})
                commands.append({'command': 'joint.solve', 'params': {}})
                write(editfile, {'commands': commands})
                subprocess.run([args.solidcraft_cli, 'eval', str(editfile), '--in', str(sc), '--json-out', str(measured)], check=True, cwd=model.ROOT, stdout=subprocess.DEVNULL)
                checks = compare(json.loads(measured.read_text(encoding='utf-8')), edit['geometry'])
                native.append({'parameter': parameter, 'value_mm': value, 'passed': all(c['passed'] for c in checks), 'body_checks': checks})
                if not native[-1]['passed']: raise AssertionError('Native edit mismatch: ' + parameter)
        print('Passed: %d bodies, %d motion poses, STEP XOR max %.9g mm3' % (len(cross), len(fcm['motion_samples']), item['maximum_step_xor_mm3']), flush=True)
    sources = [model.SOURCE, Path(__file__), model.ROOT/'scripts/tube_carrier_model.py', model.ROOT/'scripts/build_tube_carrier_freecad.py',
               model.ROOT/'scripts/robot_spec.py', model.ROOT/'scripts/build_neutral_freecad.py', model.ROOT/'scripts/freecad/persist_station_view.py', model.ROOT/'scripts/freecad/solidcraftbot_freecad.py']
    sources += [Path(model.__file__), model.ROOT/spec.get('freecad_adapter', 'scripts/build_tube_carrier_freecad.py')]
    if hasattr(model,'source_dependencies'):sources+=model.source_dependencies(spec)
    report = {'format': 'solidcraftbot.carrier-cross-cad/1', 'source': str(model.SOURCE.relative_to(model.ROOT)).replace('\\', '/'),
        'source_sha256': model.digest(model.SOURCE), 'source_files_sha256': {str(path.relative_to(model.ROOT)).replace('\\', '/'): model.digest(path) for path in sources},
        'passed': all(c['passed'] for c in reports+native), 'body_count': len(model.expanded(spec, model.parameters(spec))['bodies']),
        'cases': reports, 'solidcraft_native_parameter_edits': native, 'elapsed_s': time.monotonic()-started,
        'limitations': spec['limitations'] + ['Native edits are not written back to the shared source', 'FreeCAD colors/camera metadata saved; GUI rendering not verified',
            'Within-rigid-component contact/envelope overlaps are reported separately; these do not establish manufactured fits',
            'FreeCAD sliders use expression-driven placements rather than native Assembly solver constraints']}
    write(out/'build-report.json', report); write(model.ROOT/'cad'/family/'shared-build-report.json', report)
    print('Both native carrier models passed: cad/'+family+'/shared-build-report.json', flush=True)


if __name__ == '__main__': main()
