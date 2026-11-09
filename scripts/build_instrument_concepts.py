"""Build both independent instrument concepts in FreeCAD and SolidCraft."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from build_tube_carrier import compare
import instrument_concept as model
import tool_paths


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def relative(path):
    return str(Path(path).relative_to(model.ROOT)).replace('\\', '/')


def freecad_environment(python):
    """A bundled macOS Python needs its sibling module directory on sys.path."""
    env = os.environ.copy()
    library = Path(python).resolve().parent.parent / 'lib'
    if (library / 'FreeCAD.so').is_file():
        env['PYTHONPATH'] = str(library) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return env


def build(source_path, args):
    started = time.monotonic()
    spec = model.load(source_path)
    family = spec['family']
    stem = family + '-' + model.digest(source_path)[:12]
    revision, index = stem, 1
    while (model.ROOT / 'cad/generated' / revision).exists():
        index += 1
        revision = stem + '-r' + str(index)
    cad = model.ROOT / 'cad/generated' / revision
    out = model.ROOT / 'exports/generated' / revision
    render = model.ROOT / 'renders' / revision
    for path in (cad, out, render):
        path.mkdir(parents=True)
    sys.path.insert(0, str(model.ROOT / 'scripts/freecad'))
    from persist_station_view import persist
    cases = [('default', {}), ('raised', {'base_h': spec['parameters']['base_h']['range'][1]}),
             ('wide_deep', {k: spec['parameters'][k]['range'][1] for k in ('width', 'depth')})]
    results = []
    for name, overrides in cases:
        p = model.parameters(spec, overrides)
        prefix = cad / (spec['id'] + '_' + name)
        sc, fc = prefix.with_suffix('.sc'), prefix.with_suffix('.FCStd')
        step, commands = out / (name+'.step'), out / (name+'.commands.json')
        case_path, sc_report, fc_report = (out/(name+'.case.json'), out/(name+'.solidcraft.json'), out/(name+'.freecad.json'))
        write(commands, {'source_sha256': model.digest(source_path),
                         'commands': model.solidcraft_commands(spec, p)})
        write(case_path, {'id': name, 'overrides': overrides})
        print(f'{family}: building {name}', flush=True)
        subprocess.run([args.solidcraft_cli, 'run', str(commands), '--save', str(sc),
                        '--out', str(step), '--json-out', str(sc_report), '--quiet'],
                       check=True, cwd=model.ROOT)
        subprocess.run([args.freecad_python, str(model.ROOT/'scripts/build_instrument_concepts_freecad.py'),
                        str(source_path), str(fc), str(case_path), str(fc_report), str(step)],
                       check=True, cwd=model.ROOT, env=freecad_environment(args.freecad_python))
        native = json.loads(fc_report.read_text(encoding='utf-8'))
        comparisons = compare(json.loads(sc_report.read_text(encoding='utf-8')), native['geometry'])
        closed_script = out/(name+'.closed.commands.json')
        closed_report = out/(name+'.closed.solidcraft.json')
        write(closed_script, {'commands': [
            {'command': 'joint.drive', 'params': {'joint': 'Hinge', 'value': 0, 'quiet': True}},
            {'command': 'joint.solve', 'params': {}}]})
        subprocess.run([args.solidcraft_cli, 'eval', str(closed_script), '--in', str(sc),
                        '--json-out', str(closed_report)], check=True, cwd=model.ROOT,
                       stdout=subprocess.DEVNULL)
        closed_comparisons = compare(json.loads(closed_report.read_text(encoding='utf-8')),
                                     native['closed_geometry'])
        presentation = persist(fc, model.expanded(spec, p), native['geometry'])
        result = {'id': name, 'overrides': overrides,
                  'passed': native['passed'] and all(c['passed'] for c in comparisons + closed_comparisons) and presentation['passed'],
                  'body_comparisons': comparisons,
                  'closed_pose_body_comparisons': closed_comparisons,
                  'maximum_step_xor_mm3': max(c['xor_mm3'] for c in native['solidcraft_step_xor']),
                  'motion_samples': len(native['motion_samples']), 'freecad_presentation': presentation,
                  'interfaces': model.interfaces(spec, p),
                  'files': {k: relative(v) for k, v in {'solidcraft': sc, 'freecad': fc, 'step': step,
                                                      'solidcraft_measurements': sc_report,
                                                      'closed_solidcraft_measurements': closed_report,
                                                      'freecad_validation': fc_report, 'commands': commands}.items()},
                  'artifact_sha256': {k: model.digest(v) for k, v in {'solidcraft': sc, 'freecad': fc, 'step': step}.items()}}
        results.append(result)
        write(out/'cases-progress.json', results)
        if not result['passed']:
            raise AssertionError('Cross-CAD mismatch: ' + family + '/' + name)
    default = model.ROOT / results[0]['files']['solidcraft']
    p = model.parameters(spec)
    views = {
        'open': [],
        'closed': [{'command': 'joint.drive', 'params': {'joint': 'Hinge', 'value': 0, 'quiet': True}},
                   {'command': 'joint.solve', 'params': {}}],
        'detail': []}
    for view, commands in views.items():
        script = out/(view+'.view.json')
        write(script, {'commands': commands})
        command = [args.solidcraft_cli, 'snapshot', str(script), '--in', str(default),
                   '--out', str(render/(view+'.png')), '--width', '1300', '--height', '1000',
                   '--no-grid', '--no-axes', '--quality', 'fine']
        if view == 'detail':
            camera = {'target': [p['sample_x'], p['sample_y'], p['sample_z']+3],
                      'yaw': -0.9, 'pitch': 0.65, 'distance': 50 if family == 'nanodrop-concept' else 105}
            command += ['--camera', json.dumps(camera)]
        else:
            command += ['--view', 'iso']
        subprocess.run(command, check=True, cwd=model.ROOT)
    source_files = [source_path, Path(__file__), model.ROOT/'scripts/instrument_concept.py',
                    model.ROOT/'model/instrument-concept.schema.json',
                    model.ROOT/'scripts/build_instrument_concepts_freecad.py',
                    model.ROOT/'scripts/tube_carrier_model.py', model.ROOT/'scripts/build_tube_carrier_freecad.py',
                    model.ROOT/'scripts/build_tube_carrier.py', model.ROOT/'scripts/robot_spec.py',
                    model.ROOT/'scripts/build_neutral_freecad.py', model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',
                    model.ROOT/'scripts/freecad/persist_station_view.py', model.ROOT/'scripts/freecad/persist_view.py',
                    model.ROOT/'scripts/tool_paths.py']
    report = {'format': 'solidcraftbot.instrument-concept-build/1', 'source': relative(source_path),
              'source_sha256': model.digest(source_path),
              'source_files_sha256': {relative(p): model.digest(p) for p in source_files},
              'passed': all(c['passed'] for c in results), 'cases': results,
              'renders': {view: relative(render/(view+'.png')) for view in views},
              'render_sha256': {view: model.digest(render/(view+'.png')) for view in views},
              'body_count': len(model.expanded(spec, p)['bodies']), 'elapsed_s': time.monotonic()-started,
              'limitations': spec['limitations'] + [
                  'Sixteen discrete hinge samples per case; no continuous swept-volume proof',
                  'Within-rigid-component visual overlaps are reported and do not establish manufactured fits',
                  'FreeCAD expression-driven placements, not a native Assembly solver or physical mechanism',
                  'Geometry and dependent hinge anchors change together on regeneration from shared source',
                  'Saved FreeCAD presentation metadata checked; FreeCAD GUI rendering not verified']}
    write(out/'build-report.json', report)
    write(model.ROOT/'cad'/family/'shared-build-report.json', report)
    print(f'{family}: both CADs passed; {relative(out / "build-report.json")}', flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', choices=['all', 'nanodrop', 'qubit'], default='all')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args = parser.parse_args()
    tool_paths.resolve_tool_arguments(parser, args)
    for family, source in model.SOURCES.items():
        if args.device == 'all' or family.startswith(args.device):
            build(source, args)


if __name__ == '__main__':
    main()
