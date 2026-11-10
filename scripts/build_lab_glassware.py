"""Build referenced lab glassware in independent native CADs and validate openings."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from build_tube_carrier import compare
import lab_glassware as model
import tool_paths


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def relative(path):
    return str(Path(path).relative_to(model.ROOT)).replace('\\', '/')


def freecad_environment(python):
    env = os.environ.copy()
    library = Path(python).resolve().parent.parent/'lib'
    if (library/'FreeCAD.so').is_file():
        env['PYTHONPATH'] = str(library)+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['both', 'freecad', 'solidcraft'], default='both')
    parser.add_argument('--item', action='append', help='Build selected catalog item(s), including both closure configurations')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args = parser.parse_args()
    required = {'freecad_python', 'solidcraft_cli'} if args.backend == 'both' else {args.backend+'_python' if args.backend == 'freecad' else 'solidcraft_cli'}
    tool_paths.resolve_tool_arguments(parser, args, required=required)
    catalog = model.load()
    selected = set(args.item or catalog['items'])
    if selected-set(catalog['items']):
        parser.error('Unknown glassware items: '+', '.join(sorted(selected-set(catalog['items']))))
    started = time.monotonic()
    stem = 'lab-glassware-'+model.digest(model.SOURCE)[:12]
    revision, index = stem, 1
    while (model.ROOT/'cad/generated'/revision).exists():
        index += 1
        revision = stem+'-r'+str(index)
    cad, out, renders = (model.ROOT/folder/revision for folder in ('cad/generated', 'exports/generated', 'renders'))
    for folder in (cad, out, renders):
        folder.mkdir(parents=True)
    cases = [{'kind': 'item', 'id': model.case_id(identity, state), 'item': identity, 'state': state,
              'overrides': {}} for identity, state in model.cases(catalog) if identity in selected]
    if 'beaker_250' in selected:
        cases.append({'kind': 'item', 'id': 'beaker_250_resized', 'item': 'beaker_250', 'state': 'open',
                      'overrides': {'diameter': 76, 'height': 105}})
    full_catalog = selected == set(catalog['items'])
    if full_catalog:
        cases.append({'kind': 'overview', 'id': 'overview'})
    results = []
    sys.path.insert(0, str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    for case in cases:
        if case['kind'] == 'overview':
            spec, source, placements = model.overview(catalog)
            p = {}
            class Provider:
                SOURCE = model.SOURCE
                expanded = staticmethod(lambda spec, p: source)
                pose = staticmethod(model.pose)
                samples = staticmethod(model.samples)
            commands = model.solidcraft_commands(spec, p, Provider)
        else:
            spec = model.materialize(catalog, case['item'], case['state'], overrides=case['overrides'])
            p = model.parameters(spec)
            source = model.expanded(spec, p)
            commands = model.solidcraft_commands(spec, p)
            placements = None
        name = case['id']
        print('Glassware: '+name, flush=True)
        case_path, command_path = out/(name+'.case.json'), out/(name+'.commands.json')
        write(case_path, case)
        write(command_path, {'source_sha256': model.digest(model.SOURCE), 'commands': commands})
        paths = {'commands': command_path, 'case': case_path}
        sc, fc, step = cad/(name+'.sc'), cad/(name+'.FCStd'), out/(name+'.step')
        scm, fcm = None, None
        if args.backend in {'both', 'solidcraft'}:
            measured = out/(name+'.solidcraft.json')
            subprocess.run([args.solidcraft_cli, 'run', str(command_path), '--save', str(sc), '--out', str(step),
                            '--json-out', str(measured), '--quiet'], check=True, cwd=model.ROOT,
                           stdout=subprocess.DEVNULL)
            scm = json.loads(measured.read_text())
            paths.update(solidcraft=sc, step=step, solidcraft_measurements=measured)
        if args.backend in {'both', 'freecad'}:
            measured = out/(name+'.freecad.json')
            command = [args.freecad_python, str(model.ROOT/'scripts/build_lab_glassware_freecad.py'),
                       str(case_path), str(fc), str(measured)]
            if scm is not None:
                command += ['--compare-step', str(step)]
            subprocess.run(command, check=True, cwd=model.ROOT, env=freecad_environment(args.freecad_python))
            fcm = json.loads(measured.read_text())
            presentation = persist(fc, source, fcm['geometry'])
            paths.update(freecad=fc, freecad_validation=measured)
        else:
            presentation = None
        cross = compare(scm, fcm['geometry']) if scm is not None and fcm is not None else None
        native_ok = (fcm is None or (fcm['passed'] and presentation['passed']))
        solid_ok = (scm is None or (len(scm['bodies']) == len(source['bodies'])
                                   and all(b['closed'] and b['volume_mm3'] > 0 for b in scm['bodies'])))
        result = {'id': name, 'item': case.get('item'), 'configuration': case.get('state'),
                  'overrides': case.get('overrides'), 'passed': native_ok and solid_ok and (cross is None or all(c['passed'] for c in cross)),
                  'body_comparisons': cross, 'functional_checks': None if fcm is None else fcm['functional_checks'],
                  'interfaces': model.interfaces(spec, p) if case['kind'] == 'item' else None,
                  'geometric_clear_space_ml': model.cavity_volume_ml(spec, p) if case['kind'] == 'item' else None,
                  'nominal_volume_ml': spec['item']['nominal_volume_ml'] if case['kind'] == 'item' else None,
                  'freecad_presentation': presentation, 'placements': placements,
                  'files': {k: relative(v) for k, v in paths.items()},
                  'artifact_sha256': {k: model.digest(v) for k, v in paths.items() if k in {'freecad', 'solidcraft', 'step'}}}
        results.append(result)
        write(out/'cases-progress.json', results)
        if not result['passed']:
            raise AssertionError('Glassware validation failed: '+name)
    views = {}
    if args.backend in {'both', 'solidcraft'}:
        empty = out/'view.commands.json'
        write(empty, {'commands': []})
        for name in (['overview'] if full_catalog else [results[0]['id']]):
            image = renders/(name+'.png')
            command = [args.solidcraft_cli, 'snapshot', str(empty), '--in', str(cad/(name+'.sc')),
                       '--out', str(image), '--width', '1800', '--height', '560',
                       '--no-grid', '--no-axes', '--quality', 'fine']
            camera = None
            if name == 'overview':
                overview_case = next(c for c in results if c['id'] == name)
                bounds = json.loads((model.ROOT/overview_case['files']['solidcraft_measurements']).read_text())['bodies']
                lo = [min(b['bbox']['min'][i] for b in bounds) for i in range(3)]
                hi = [max(b['bbox']['max'][i] for b in bounds) for i in range(3)]
                width, depth, height = [b-a for a, b in zip(lo, hi)]
                fov, pitch = .6, .4
                distance = max(width/(1800/560), height*math.cos(pitch)+depth*math.sin(pitch))
                camera = {'target': [(a+b)/2 for a, b in zip(lo, hi)], 'yaw': 0, 'pitch': pitch,
                          'distance': distance*1.1/(2*math.tan(fov/2))+depth/2, 'fov': fov}
                command += ['--camera', json.dumps(camera)]
            else:
                command += ['--view', 'iso']
            subprocess.run(command, check=True, cwd=model.ROOT,
                           stdout=subprocess.DEVNULL)
            views[name] = {'path': relative(image), 'sha256': model.digest(image),
                           'source': 'native SolidCraft model', 'camera': camera, 'size_px': [1800, 560]}
    sources = [model.SOURCE, model.ROOT/'model/lab-glassware.schema.json', Path(__file__), Path(model.__file__),
               model.ROOT/'scripts/build_lab_glassware_freecad.py', model.ROOT/'scripts/tube_carrier_model.py',
               model.ROOT/'scripts/build_tube_carrier.py', model.ROOT/'scripts/build_tube_carrier_freecad.py',
               model.ROOT/'scripts/assembly_model.py', model.ROOT/'scripts/robot_spec.py',
               model.ROOT/'scripts/build_neutral_freecad.py', model.ROOT/'scripts/tool_paths.py',
               model.ROOT/'scripts/freecad/solidcraftbot_freecad.py', model.ROOT/'scripts/freecad/persist_station_view.py',
               model.ROOT/'scripts/freecad/persist_view.py']
    report = {'format': 'solidcraftbot.lab-glassware-build/1', 'source': relative(model.SOURCE),
              'source_sha256': model.digest(model.SOURCE), 'source_files_sha256': {relative(p): model.digest(p) for p in sources},
              'passed': all(c['passed'] for c in results), 'backends': args.backend,
              'complete_catalog': full_catalog, 'cross_cad_checked': args.backend == 'both',
              'native_functional_checks_run': args.backend in {'both', 'freecad'},
              'cases': results, 'renders': views, 'elapsed_s': time.monotonic()-started,
              'limitations': catalog['limitations'] + [
                  'Stored interface frames describe the generated source revision; regenerate after native dimension edits.',
                  'The beaker clear-space volume stops below the spout root and excludes the pouring trough.',
                  'The funnel void is a through passage, not retained liquid capacity.',
                  'The overview is a derived contact sheet without a bench, holder or operational scene.',
                  'FreeCAD presentation metadata is checked; its GUI rendering is not verified.']}
    write(out/'build-report.json', report)
    latest = model.ROOT/'cad/lab-glassware'
    latest.mkdir(exist_ok=True)
    write(latest/'shared-build-report.json', report)
    print('Glassware passed: '+relative(out/'build-report.json'), flush=True)


if __name__ == '__main__':
    main()
