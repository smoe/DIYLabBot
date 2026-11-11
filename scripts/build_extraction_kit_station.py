"""Build the K01 kit-station concept independently in either native CAD backend."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

import extraction_kit_station as model
import robot_spec
import tool_paths

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.extraction-kit-station-build/1'
CASES = {'stored', 'open', 'wide_open'}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT.resolve())).replace('\\', '/')


def required_tools(backend):
    if backend not in {'freecad', 'solidcraft', 'both'}:
        raise ValueError('Unknown CAD backend')
    return ({'freecad_python'} if backend == 'freecad' else {'solidcraft_cli'}
            if backend == 'solidcraft' else {'freecad_python', 'solidcraft_cli'})


def source_snapshot(spec, source):
    paths = [Path(source), Path(__file__), ROOT/'scripts/build_extraction_kit_station_freecad.py',
             ROOT/'scripts/extraction_kit_station.py', ROOT/'model/extraction-kit-station.schema.json',
             ROOT/'scripts/tube_carrier_model.py', ROOT/'scripts/build_tube_carrier_freecad.py',
             ROOT/'scripts/robot_spec.py', ROOT/'scripts/robot_cameras.py', ROOT/'scripts/build_neutral_freecad.py',
             ROOT/'scripts/assembly_model.py', ROOT/'model/assembly-reference.schema.json',
             ROOT/'scripts/freecad/solidcraftbot_freecad.py',
             ROOT/'scripts/freecad/persist_station_view.py', ROOT/'scripts/freecad/persist_view.py',
             ROOT/'scripts/tool_paths.py']
    paths.extend(model.source_dependencies(spec))
    result = {}
    for path in paths:
        path = Path(path)
        if not path.is_absolute():
            path = ROOT/path
        result[relative(path)] = robot_spec.digest(path)
    return result


def verify_pins(pins):
    if not pins:
        raise ValueError('Source pins required')
    for name, expected in pins.items():
        path = (ROOT/name).resolve()
        if (not path.is_relative_to(ROOT.resolve()) or not path.is_file()
                or robot_spec.digest(path) != expected):
            raise ValueError('Build source changed: '+name)


def freecad_environment(python):
    env = os.environ.copy()
    library = Path(python).resolve().parent.parent/'lib'
    if (library/'FreeCAD.so').is_file():
        env['PYTHONPATH'] = str(library)+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return env


def measurements(report, source, *, backend):
    """Validate IDs/closed solids and normalize the two native measurement forms."""
    bodies = report['bodies'] if backend == 'solidcraft' else report['geometry']
    expected = [body['id'] for body in source['bodies']]
    actual = [body['name' if backend == 'solidcraft' else 'body'] for body in bodies]
    if len(set(expected)) != len(expected) or len(set(actual)) != len(actual) or set(actual) != set(expected):
        raise ValueError('Body identity/count mismatch')
    result = []
    for body, name in zip(bodies, actual):
        closed = (body.get('closed') is True if backend == 'solidcraft'
                  else body.get('valid') is True and body.get('solid_count') == 1)
        center = body['center_of_mass' if backend == 'solidcraft' else 'world_center_of_mass_mm']
        values = [body['volume_mm3'], *center, *body['bbox']['min'], *body['bbox']['max']]
        if (not closed or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                or body['volume_mm3'] <= 0 or len(center) != 3
                or any(len(body['bbox'][key]) != 3 for key in ('min', 'max'))
                or any(a >= b for a, b in zip(body['bbox']['min'], body['bbox']['max']))):
            raise ValueError('Invalid closed solid: '+name)
        result.append({'body': name, 'volume_mm3': body['volume_mm3'],
                       'world_center_of_mass_mm': center, 'bbox': body['bbox']})
    return result


def compare(actual, expected):
    by_name = {body['body']: body for body in expected}
    if len(by_name) != len(expected) or len({b['body'] for b in actual}) != len(actual) or set(by_name) != {b['body'] for b in actual}:
        raise ValueError('Cross-CAD body identity/count mismatch')
    result = []
    for body in actual:
        ref = by_name[body['body']]
        volume = abs(body['volume_mm3']-ref['volume_mm3'])/ref['volume_mm3']
        center = math.dist(body['world_center_of_mass_mm'], ref['world_center_of_mass_mm'])
        bounds = max(abs(a-b) for key in ('min', 'max') for a, b in zip(body['bbox'][key], ref['bbox'][key]))
        result.append({'body': body['body'], 'relative_volume_error': volume,
                       'com_error_mm': center, 'bbox_error_mm': bounds,
                       'passed': volume < .001 and center < .01 and bounds < .01})
    return result


def interface_checks(spec, p, geometry):
    checks = model.check_interface_geometry(spec, p, geometry)
    if not checks or len({c['id'] for c in checks}) != len(checks):
        raise ValueError('Explicit, unique native interface checks required')
    return checks


def check_solidcraft_interference(results, count):
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise ValueError('Missing SolidCraft interference result')
    result = results[0]
    required = {'checked', 'count', 'interferences', 'unchecked', 'truncated', 'budget_exceeded',
                'pairs_not_checked', 'skipped_pairs'}
    if not required <= set(result):
        raise ValueError('Incomplete SolidCraft interference evidence')
    passed = (result['checked'] == count and result['count'] == 0 and not result['interferences']
              and not result['unchecked'] and result['truncated'] is False
              and result['budget_exceeded'] is False and result['pairs_not_checked'] == 0
              and result['skipped_pairs'] == 0)
    return {**result, 'passed': passed, 'scope': 'All native bodies at this static source-defined pose'}


def clearance_probes(spec, p):
    """Resolve source-derived, unqualified finger/approach envelopes, with margin."""
    probes = model.interfaces(spec, p).get('native_clearance_probes')
    if not isinstance(probes, list) or not probes:
        raise ValueError('Native handle/approach clearance probes required')
    identities = set()
    result = []
    for probe in probes:
        required = {'id', 'frame_id', 'kind', 'origin_mm', 'size_mm', 'minimum_clearance_mm'}
        if not isinstance(probe, dict) or not required <= set(probe):
            raise ValueError('Incomplete native clearance probe')
        if (not isinstance(probe['id'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', probe['id'])
                or probe['id'] in identities or not isinstance(probe['frame_id'], str) or not probe['frame_id']
                or probe['kind'] != 'box'):
            raise ValueError('Unique named box clearance probes required')
        origin, size, margin = probe['origin_mm'], probe['size_mm'], probe['minimum_clearance_mm']
        if (not isinstance(origin, list) or not isinstance(size, list) or len(origin) != 3 or len(size) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in origin+size+[margin]) or min(size) <= 0 or margin <= 0):
            raise ValueError('Finite probe geometry and positive clearance required')
        identities.add(probe['id'])
        # A cube offset contains the Euclidean ball offset: an empty expanded
        # box conservatively certifies this margin for the declared box only.
        result.append({**probe, 'audit_origin_mm': [value-margin for value in origin],
                       'audit_size_mm': [value+2*margin for value in size],
                       'grasp_qualified': False})
    return result


def solidcraft_clearances(args, spec, p, native_path, out, case_id, geometry, paths):
    checks = []
    original = robot_spec.digest(native_path)
    names = [body['body'] for body in geometry]
    for probe in clearance_probes(spec, p):
        body = 'K01_Audit_'+probe['id']
        if body in names:
            raise ValueError('Clearance probe collides with a native body identity')
        script = out/(case_id+'.'+probe['id']+'.clearance.commands.json')
        report = out/(case_id+'.'+probe['id']+'.clearance.json')
        write(script, {'commands': [
            {'command': 'solid.box', 'params': {'operation': 'new', 'name': body, 'body_name': body,
                'corner': probe['audit_origin_mm'],
                **dict(zip(('length', 'width', 'height'), probe['audit_size_mm']))}},
            {'command': 'inspect.interference', 'params': {'bodies': names+[body]}}]})
        subprocess.run([args.solidcraft_cli, 'run', str(script), '--in', str(native_path),
                        '--results', '--quiet', '--json-out', str(report)],
                       check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        if robot_spec.digest(native_path) != original:
            raise ValueError('Clearance audit changed native CAD input')
        raw = json.loads(report.read_text(encoding='utf-8'))
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError('Incomplete SolidCraft probe construction/audit results')
        inspection = check_solidcraft_interference(raw[-1:], len(names)+1)
        checks.append({**probe, 'passed': inspection['passed'], 'interference': inspection,
                       'native_bodies_checked': names,
                       'method': 'Native solid.box offset-envelope versus every saved model solid; no input save'})
        paths['clearance_'+probe['id']+'_commands'] = script
        paths['clearance_'+probe['id']+'_result'] = report
    return {'passed': all(check['passed'] for check in checks), 'checks': checks,
            'scope': 'Static source-defined finger and approach envelopes; no real gripper or execution qualification'}


def verify_artifacts(paths, pins):
    for name, digest in pins.items():
        if robot_spec.digest(paths[name]) != digest:
            raise ValueError('Generated artifact changed: '+name)


def render_cases(args, cases, render_dir, pins):
    renders = {}
    for name in ('stored', 'open'):
        case = next(case for case in cases if case['id'] == name)
        native = ROOT/case['files']['solidcraft']
        before = robot_spec.digest(native)
        image = render_dir/(name+'.png')
        command = [args.solidcraft_cli, 'snapshot', '--in', str(native), '--out', str(image),
                   '--width', '1300', '--height', '900', '--view', 'iso',
                   '--no-grid', '--no-axes', '--quality', 'fine']
        subprocess.run(command, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        if robot_spec.digest(native) != before:
            raise ValueError('Rendering changed native CAD input')
        verify_pins(pins)
        renders[name] = {'path': relative(image), 'sha256': robot_spec.digest(image),
                         'pixels': [1300, 900], 'source': 'model', 'visually_reviewed': False}
    return renders


def build(args):
    started = time.monotonic()
    source_path = Path(args.source).resolve()
    relative(source_path)
    model.SOURCE = source_path
    source_hash = robot_spec.digest(source_path)
    spec = model.load(source_path)
    pins = source_snapshot(spec, source_path)
    if pins[relative(source_path)] != source_hash:
        raise ValueError('Source changed while loading')
    verify_pins(pins)
    case_ids = [case if isinstance(case, str) else case['id'] for case in model.cases(spec)]
    if len(case_ids) != 3 or set(case_ids) != CASES:
        raise ValueError('stored/open/wide_open static cases required')
    stem = 'extraction-kit-station-'+source_hash[:12]
    revision, number = stem, 1
    while any((ROOT/folder/revision).exists() for folder in ('cad/generated', 'exports/generated', 'renders')):
        number += 1
        revision = stem+'-r'+str(number)
    cad, out, render = (ROOT/folder/revision for folder in ('cad/generated', 'exports/generated', 'renders'))
    for directory in (cad, out, render):
        directory.mkdir(parents=True)
    results = []
    for case_id in case_ids:
        verify_pins(pins)
        current = model.materialize(spec, case_id)
        p = model.parameters(current)
        expanded = model.expanded(current, p)
        if expanded['joints']:
            raise ValueError('K01 is a static concept, not a motion program')
        paths = {'case': out/(case_id+'.case.json')}
        write(paths['case'], {'id': case_id, 'source': relative(source_path),
                             'source_sha256': source_hash, 'source_files_sha256': pins})
        print('K01: '+case_id+' ('+args.backend+')', flush=True)
        sc_geometry = fc_geometry = None
        sc_checks = fc_checks = None
        if args.backend in {'solidcraft', 'both'}:
            paths.update(commands=out/(case_id+'.commands.json'), solidcraft=cad/(case_id+'.sc'),
                         solidcraft_measurements=out/(case_id+'.solidcraft.json'))
            write(paths['commands'], {'source_sha256': source_hash, 'commands': model.solidcraft_commands(current, p)})
            command = [args.solidcraft_cli, 'run', str(paths['commands']), '--save', str(paths['solidcraft']),
                       '--json-out', str(paths['solidcraft_measurements']), '--quiet']
            if args.backend == 'both':
                paths['step'] = out/(case_id+'.step')
                command.extend(['--out', str(paths['step'])])
            subprocess.run(command, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
            raw = json.loads(paths['solidcraft_measurements'].read_text(encoding='utf-8'))
            sc_geometry = measurements(raw, expanded, backend='solidcraft')
            paths.update(solidcraft_interference_commands=out/(case_id+'.interference.commands.json'),
                         solidcraft_interference=out/(case_id+'.interference.json'))
            write(paths['solidcraft_interference_commands'], {'commands': [
                {'command': 'inspect.interference', 'params': {'bodies': [b['body'] for b in sc_geometry]}}]})
            subprocess.run([args.solidcraft_cli, 'run', str(paths['solidcraft_interference_commands']),
                            '--in', str(paths['solidcraft']), '--results', '--quiet',
                            '--json-out', str(paths['solidcraft_interference'])],
                           check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
            interference = check_solidcraft_interference(json.loads(paths['solidcraft_interference'].read_text()), len(sc_geometry))
            interfaces = interface_checks(current, p, sc_geometry)
            clearances = solidcraft_clearances(args, current, p, paths['solidcraft'], out, case_id, sc_geometry, paths)
            sc_checks = {'passed': interference['passed'] and clearances['passed'] and all(c['passed'] for c in interfaces),
                         'interfaces': interfaces, 'interference': interference,
                         'handle_approach_clearances': clearances,
                         'construction': 'Direct shared operations; no FreeCAD input'}
        if args.backend in {'freecad', 'both'}:
            paths.update(freecad=cad/(case_id+'.FCStd'), freecad_validation=out/(case_id+'.freecad.json'))
            command = [args.freecad_python, str(ROOT/'scripts/build_extraction_kit_station_freecad.py'),
                       str(paths['case']), str(paths['freecad']), str(paths['freecad_validation'])]
            if args.backend == 'both':
                command.extend(['--compare-step', str(paths['step'])])
            subprocess.run(command, check=True, cwd=ROOT, env=freecad_environment(args.freecad_python))
            fc_checks = json.loads(paths['freecad_validation'].read_text(encoding='utf-8'))
            if (fc_checks['source_sha256'] != source_hash or fc_checks['source_files_sha256'] != pins
                    or fc_checks['case'] != case_id):
                raise ValueError('FreeCAD evidence belongs to different inputs')
            fc_geometry = measurements(fc_checks, expanded, backend='freecad')
        cross = compare(sc_geometry, fc_geometry) if args.backend == 'both' else None
        passed = ((sc_checks is None or sc_checks['passed']) and (fc_checks is None or fc_checks['passed'])
                  and (cross is None or all(c['passed'] for c in cross)))
        item = {'id': case_id, 'passed': passed, 'body_count': len(expanded['bodies']),
                'interfaces': model.interfaces(current, p), 'body_comparisons': cross,
                'cross_cad_checked': args.backend == 'both' and passed,
                'solidcraft_checks': sc_checks, 'freecad_checks_passed': None if fc_checks is None else fc_checks['passed'],
                'maximum_step_xor_mm3': (max(c['xor_mm3'] for c in fc_checks['solidcraft_step_xor'])
                                         if args.backend == 'both' else None),
                'files': {key: relative(path) for key, path in paths.items()},
                'artifact_sha256': {key: robot_spec.digest(path) for key, path in paths.items()}}
        results.append(item)
        write(out/'cases-progress.json', results)
        verify_pins(pins)
        if not passed:
            raise AssertionError('K01 native checks failed: '+case_id)
    renders = (render_cases(args, results, render, pins)
               if args.backend in {'solidcraft', 'both'} and not args.no_render else {})
    verify_pins(pins)
    for case in results:
        verify_artifacts({key: ROOT/path for key, path in case['files'].items()}, case['artifact_sha256'])
    report = {'format': FORMAT, 'source': relative(source_path), 'source_sha256': source_hash,
              'source_files_sha256': pins, 'revision': revision, 'backends': args.backend,
              'cross_cad_checked': args.backend == 'both' and all(case['passed'] for case in results),
              'passed': all(case['passed'] for case in results), 'cases': results, 'renders': renders,
              'elapsed_s': time.monotonic()-started,
              'comparison_tolerances': {'relative_volume_error': .001, 'com_error_mm': .01,
                                       'bbox_error_mm': .01, 'step_xor_mm3': .001,
                                       'freecad_interference_volume_mm3': .00001},
              'limitations': list(spec.get('limitations', []))+[
                  'Three static source-defined cases; no robot movement or access trajectory is generated or qualified',
                  'Offset-box clearance probes cover only source-defined synthetic finger/approach envelopes; no real grasp qualification',
                  'Manufacturer vessels and contents are unmeasured illustrative envelopes, not purchase-part CAD',
                  'Closed solids and static clearances do not qualify FDM/PETG, chemical resistance, SDS suitability or real fit',
                  'No extraction, dosing, contamination control, reagent storage conditions or hardware execution tested',
                  'Saved FreeCAD presentation metadata checked; no FreeCAD GUI rendering verified',
                  'Backend-only reports do not establish a cross-CAD comparison']}
    write(out/'build-report.json', report)
    verify_pins(pins)
    write(ROOT/'cad/extraction-kit-station/shared-build-report.json', report)
    print('K01 native build passed: '+relative(out/'build-report.json'), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['freecad', 'solidcraft', 'both'], default='both')
    parser.add_argument('--source', default=str(model.SOURCE))
    parser.add_argument('--no-render', action='store_true', help='Omit optional SolidCraft preview images')
    tool_paths.add_tool_arguments(parser)
    args = parser.parse_args(argv)
    requested = required_tools(args.backend)
    tools = argparse.Namespace(**{name: getattr(args, name) for name in requested})
    tool_paths.resolve_tool_arguments(parser, tools, required=requested)
    for name in requested:
        setattr(args, name, getattr(tools, name))
    return build(args)


if __name__ == '__main__':
    main()
