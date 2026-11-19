"""Generate the assumed dual-syringe concept independently in either CAD."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from build_instrument_concepts import freecad_environment
from build_tube_carrier import compare
import syringe_pipette as model
import tool_paths


CASES = (
    {'id': 'default', 'head': 'micro', 'overrides': {}},
    {'id': 'radius_variant', 'head': 'micro', 'overrides': {'radiusFine': 2.6, 'radiusCoarse': 8.0}},
    {'id': 'wide', 'head': 'micro', 'overrides': {'spacing': 135}},
    {'id': 'macro', 'head': 'macro', 'overrides': {}},
)


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def relative(path):
    return str(Path(path).relative_to(model.ROOT)).replace('\\', '/')


def drive_commands(values):
    return [{'command': 'joint.drive', 'params': {'joint': name, 'value': value, 'quiet': True}}
            for name, value in values.items()]+[{'command': 'joint.solve', 'params': {}}]


def parameters_argument(values):
    overrides = {}
    for entry in values:
        if '=' not in entry:
            raise ValueError('Use --parameter name=value')
        name, text = entry.split('=', 1)
        if not name or name in overrides:
            raise ValueError('Parameter overrides need unique names')
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('Parameter overrides must be finite')
        overrides[name] = value
    return overrides


def source_files(spec):
    names = [model.SOURCE, Path(__file__), Path(model.__file__),
        model.ROOT/'model/syringe-pipette.schema.json',
        model.ROOT/'scripts/build_syringe_pipette_freecad.py',
        model.ROOT/'scripts/tube_carrier_model.py', model.ROOT/'scripts/build_tube_carrier_freecad.py',
        model.ROOT/'scripts/build_tube_carrier.py', model.ROOT/'scripts/robot_spec.py',
        model.ROOT/'scripts/tube_cam_model.py', model.ROOT/'scripts/tube_frame_model.py',
        model.ROOT/'scripts/build_neutral_freecad.py', model.ROOT/'scripts/instrument_concept.py',
        model.ROOT/'scripts/build_instrument_concepts.py', model.ROOT/'scripts/tool_paths.py',
        model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',
        model.ROOT/'scripts/freecad/persist_station_view.py', model.ROOT/'scripts/freecad/persist_view.py']
    if hasattr(model, 'source_dependencies'):
        names += model.source_dependencies(spec)
    return sorted(set(map(Path, names)))


def build(args):
    started = time.monotonic()
    spec = model.load()
    base_overrides = parameters_argument(args.parameter)
    selected = set(args.case or [row['id'] for row in CASES])
    unknown = selected-{row['id'] for row in CASES}
    if unknown:
        raise ValueError('Unknown build case: '+str(sorted(unknown)))
    cases = [{**row, 'overrides': {**base_overrides, **row['overrides']}}
             for row in CASES if row['id'] in selected]
    for case in cases:
        model.parameters(spec, case['overrides'])
    pins = {relative(path): model.digest(path) for path in source_files(spec)}
    stem = 'syringe-pipette-'+model.digest(model.SOURCE)[:12]
    revision, counter = stem, 1
    while (model.ROOT/'cad/generated'/revision).exists():
        counter += 1
        revision = stem+'-r'+str(counter)
    cad, out, renders = (model.ROOT/folder/revision for folder in ('cad/generated', 'exports/generated', 'renders'))
    for directory in (cad, out, renders):
        directory.mkdir(parents=True)
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist

    results = []
    for case in cases:
        print('Syringe concept: '+case['id'], flush=True)
        p = model.parameters(spec, case['overrides'])
        source = model.expanded(spec, p, head=case['head'])
        identity = case['id']
        case_path, commands_path = out/(identity+'.case.json'), out/(identity+'.commands.json')
        write(case_path, case)
        files = {'case': case_path}
        sc, fc, step = cad/(identity+'.sc'), cad/(identity+'.FCStd'), out/(identity+'.step')
        scm, fcm, presentation = None, None, None
        if args.backend in {'both', 'solidcraft'}:
            write(commands_path, {'source_sha256': model.digest(model.SOURCE),
                                 'commands': model.solidcraft_commands(spec, p, head=case['head'])})
            measure = out/(identity+'.solidcraft.json')
            subprocess.run([args.solidcraft_cli, 'run', str(commands_path), '--save', str(sc),
                '--out', str(step), '--json-out', str(measure), '--quiet'], check=True, cwd=model.ROOT)
            scm = json.loads(measure.read_text(encoding='utf-8'))
            files.update(commands=commands_path, solidcraft=sc, step=step, solidcraft_measurements=measure)
        if args.backend in {'both', 'freecad'}:
            validation = out/(identity+'.freecad.json')
            command = [args.freecad_python, str(model.ROOT/'scripts/build_syringe_pipette_freecad.py'),
                       str(case_path), str(fc), str(validation)]
            if scm is not None:
                command += ['--compare-step', str(step)]
            subprocess.run(command, check=True, cwd=model.ROOT, env=freecad_environment(args.freecad_python))
            fcm = json.loads(validation.read_text(encoding='utf-8'))
            presentation = persist(fc, source, fcm['geometry'])
            files.update(freecad=fc, freecad_validation=validation)
        cross = compare(scm, fcm['geometry']) if scm is not None and fcm is not None else None
        named_cross = []
        if scm is not None and fcm is not None:
            for sample in model.build_samples(spec, p):
                name = sample['id']
                values = sample.get('joint_values', sample.get('values_mm'))
                script, measured = out/(identity+'.'+name+'.commands.json'), out/(identity+'.'+name+'.solidcraft.json')
                write(script, {'commands': drive_commands(values)})
                subprocess.run([args.solidcraft_cli, 'eval', str(script), '--in', str(sc),
                    '--json-out', str(measured)], check=True, cwd=model.ROOT, stdout=subprocess.DEVNULL)
                checks = compare(json.loads(measured.read_text(encoding='utf-8')), fcm['named_pose_geometry'][name])
                named_cross.append({'id': name, 'passed': all(row['passed'] for row in checks),
                                    'body_comparisons': checks, 'measurements': relative(measured)})
                files['pose_'+name] = measured
        native_ok = fcm is None or fcm['passed']
        sc_ok = scm is None or bool(scm['bodies']) and all(row['closed'] and row['volume_mm3'] > 0 for row in scm['bodies'])
        passed = native_ok and sc_ok and (cross is None or all(row['passed'] for row in cross))
        passed = passed and all(row['passed'] for row in named_cross) and (presentation is None or presentation['passed'])
        result = {**case, 'passed': passed, 'parameter_values': p,
            'body_count': len(source['bodies']), 'body_comparisons': cross, 'named_pose_comparisons': named_cross,
            'freecad_presentation': presentation,
            'collision_free_samples': fcm['collision_free_samples'] if fcm else None,
            'interfaces': model.interfaces(spec, p, head=case['head']),
            'files': {key: relative(path) for key, path in files.items()},
            'artifact_sha256': {key: model.digest(path) for key, path in files.items()}}
        results.append(result)
        write(out/'cases-progress.json', results)
        if not passed:
            raise AssertionError('Syringe concept geometry comparison failed: '+identity)

    views = {}
    if args.backend in {'both', 'solidcraft'} and not args.no_render:
        for case in cases:
            if case['id'] not in {'default', 'macro'}:
                continue
            source_file = model.ROOT/next(row for row in results if row['id'] == case['id'])['files']['solidcraft']
            poses = ('fine', 'head_removed') if case['id'] == 'default' else ('fine',)
            p = model.parameters(spec, case['overrides'])
            for pose_name in poses:
                name = case['id']+'_'+pose_name
                script, image = out/(name+'.view.json'), renders/(name+'.png')
                write(script, {'commands': drive_commands(model.pose(spec, p, pose_name))})
                subprocess.run([args.solidcraft_cli, 'snapshot', str(script), '--in', str(source_file),
                    '--out', str(image), '--width', '1400', '--height', '1100', '--view', 'iso',
                    '--quality', 'fine', '--no-grid', '--no-axes'], check=True, cwd=model.ROOT)
                views[name] = {'path': relative(image), 'sha256': model.digest(image)}
    if any(model.digest(model.ROOT/name) != digest for name, digest in pins.items()):
        raise ValueError('Sources changed while building; do not reuse this proof')
    report = {'format': 'solidcraftbot.syringe-pipette-build/1', 'passed': all(row['passed'] for row in results),
        'revision': revision, 'source': relative(model.SOURCE), 'source_sha256': model.digest(model.SOURCE),
        'source_files_sha256': pins, 'backends': args.backend, 'cross_cad_checked': args.backend == 'both',
        'cases': results, 'renders': views, 'elapsed_s': time.monotonic()-started,
        'qualification': {'dimensions_measured': False, 'gas_tightness_qualified': False,
                          'dosing_accuracy_qualified': False, 'hardware_motion_qualified': False},
        'limitations': spec['limitations']+[
            'Native geometry, parameter variants and sampled joint placement are checked; no physical pipetting simulation.',
            'All native interferences are reported separately; manufactured fits and continuous collision freedom are unqualified.',
            'FreeCAD presentation metadata is persisted; no FreeCAD GUI rendering is asserted.',
            'A drawn Luer connector is a concept envelope without certified standard dimensions or gas leakage results.']}
    write(out/'build-report.json', report)
    latest = model.ROOT/'cad/syringe-pipette'
    latest.mkdir(parents=True, exist_ok=True)
    write(latest/'shared-build-report.json', report)
    print('Syringe concept passed: '+str(out/'build-report.json'), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['both', 'freecad', 'solidcraft'], default='both')
    parser.add_argument('--case', action='append', choices=[row['id'] for row in CASES])
    parser.add_argument('--parameter', action='append', default=[], metavar='NAME=VALUE',
                        help='Override a driving parameter; dedicated variant overrides take precedence')
    parser.add_argument('--no-render', action='store_true')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args = parser.parse_args()
    needed = {'freecad_python', 'solidcraft_cli'} if args.backend == 'both' else {
        'freecad_python' if args.backend == 'freecad' else 'solidcraft_cli'}
    tool_paths.resolve_tool_arguments(parser, args, required=needed)
    return build(args)


if __name__ == '__main__':
    main()
