"""Independent native CAD builds of two static, supported S01 storage states."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import time

import build_extraction_kit_station as common
import kit_storage_model as model
import tool_paths

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.kit-storage-build/1'
CASES = {'shelf', 'handover'}
CONTACT_DEPTH_MM = .1  # Geometric witness only; not a physical design dimension.
write, relative = common.write, common.relative


def source_snapshot(spec, source):
    paths = [source, Path(__file__), ROOT/'scripts/build_kit_storage_freecad.py',
             ROOT/'scripts/build_extraction_kit_station.py', ROOT/'scripts/build_tube_carrier_freecad.py',
             ROOT/'scripts/build_neutral_freecad.py', ROOT/'scripts/robot_cameras.py',
             ROOT/'scripts/freecad/solidcraftbot_freecad.py', ROOT/'scripts/freecad/persist_station_view.py',
             ROOT/'scripts/freecad/persist_view.py', ROOT/'scripts/tool_paths.py',
             *model.source_dependencies(spec)]
    return {relative(path): common.robot_spec.digest(path) for path in paths}


def probe_boxes(spec, p):
    probes = model.interfaces(spec, p)['native_clearance_probes']
    if not probes or len({probe['id'] for probe in probes}) != len(probes):
        raise ValueError('Complete, unique access probes required')
    result = []
    for probe in probes:
        origin, size, margin = probe['origin_mm'], probe['size_mm'], probe['minimum_clearance_mm']
        if (not isinstance(probe['id'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', probe['id']) or probe['kind'] != 'box'
                or not isinstance(probe['frame_id'], str) or not probe['frame_id'] or len(origin) != 3 or len(size) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in origin+size+[margin])
                or min(size) <= 0 or margin <= 0):
            raise ValueError('Invalid source-derived access box')
        result.append({**probe, 'audit_origin_mm': [v-margin for v in origin],
                       'audit_size_mm': [v+2*margin for v in size], 'grasp_qualified': False})
    return result


def support_geometry(spec, p, geometry):
    contract = model.interfaces(spec, p)['support']
    bodies = {body['body']: body for body in geometry}
    carrier, support = bodies[contract['carrier_body']], bodies[contract['support_body']]
    footprint, z = contract['footprint_bbox_mm'], contract['contact_z_mm']
    lo, hi = footprint['min'], footprint['max']
    if (len(lo) != 3 or len(hi) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in lo+hi+[z])
            or hi[0] <= lo[0] or hi[1] <= lo[1] or abs(lo[2]-z) > 1e-7 or abs(hi[2]-z) > 1e-7):
        raise ValueError('Positive planar support footprint required')
    area = (hi[0]-lo[0])*(hi[1]-lo[1])
    passed = (abs(carrier['bbox']['min'][2]-z) < 1e-7 and abs(support['bbox']['max'][2]-z) < 1e-7
              and all(support['bbox']['min'][i] <= lo[i]+1e-7 and support['bbox']['max'][i] >= hi[i]-1e-7 for i in (0, 1)))
    return {**contract, 'passed': passed, 'footprint_area_mm2': area,
            'witness_origin_mm': [lo[0], lo[1], z-CONTACT_DEPTH_MM],
            'witness_size_mm': [hi[0]-lo[0], hi[1]-lo[1], 2*CONTACT_DEPTH_MM],
            'expected_half_volume_mm3': area*CONTACT_DEPTH_MM,
            'witness_depth_each_side_mm': CONTACT_DEPTH_MM,
            'scope': 'Geometric footprint/z alignment with native thin-slab intersections; no physical contact, load, retention or stability qualification'}


def support_volumes(contract, volumes):
    expected = contract['expected_half_volume_mm3']
    tolerance = max(1e-5, expected*1e-7)
    required = {contract['carrier_body'], contract['support_body']}
    passed = (contract['passed'] and set(volumes) == required
              and all(type(v) in (int, float) and math.isfinite(v) and abs(v-expected) <= tolerance for v in volumes.values()))
    return {**contract, 'passed': passed, 'witness_intersections_mm3': volumes,
            'volume_tolerance_mm3': tolerance}


def support_intersection(raw, target, witness):
    required = {'checked', 'count', 'interferences', 'unchecked', 'truncated', 'budget_exceeded',
                'pairs_not_checked', 'skipped_pairs'}
    if (not isinstance(raw, dict) or not required <= set(raw) or raw['checked'] != 2
            or raw['count'] != 1 or len(raw['interferences']) != 1 or raw['unchecked']
            or raw['truncated'] is not False or raw['budget_exceeded'] is not False
            or raw['pairs_not_checked'] != 0 or raw['skipped_pairs'] != 0):
        raise ValueError('Complete native support intersection required')
    hit = raw['interferences'][0]
    if {hit['a'], hit['b']} != {target, witness}:
        raise ValueError('Support evidence refers to another body pair')
    return hit['volume_mm3']


def solidcraft_query(args, native, commands, out, identity, paths):
    script, result = out/(identity+'.commands.json'), out/(identity+'.result.json')
    write(script, {'commands': commands})
    before = common.robot_spec.digest(native)
    subprocess.run([args.solidcraft_cli, 'run', str(script), '--in', str(native), '--results',
                    '--quiet', '--json-out', str(result)], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    if common.robot_spec.digest(native) != before:
        raise ValueError('Native audit modified the saved scene')
    raw = json.loads(result.read_text())
    if not isinstance(raw, list) or len(raw) != len(commands):
        raise ValueError('Incomplete native command results')
    paths[identity+'_commands'], paths[identity+'_results'] = script, result
    return raw


def box_command(name, origin, size):
    return {'command': 'solid.box', 'params': {'operation': 'new', 'name': name, 'body_name': name,
            'corner': origin, **dict(zip(('length', 'width', 'height'), size))}}


def solidcraft_checks(args, spec, p, native, out, case, geometry, paths):
    names = [body['body'] for body in geometry]
    raw = solidcraft_query(args, native, [{'command': 'inspect.interference', 'params': {'bodies': names}}],
                           out, case+'_interference', paths)
    interference = common.check_solidcraft_interference(raw, len(names))
    probes = []
    for probe in probe_boxes(spec, p):
        witness = 'S01_Probe_'+probe['id']
        if witness in names:
            raise ValueError('Probe identity collides with scene body')
        raw = solidcraft_query(args, native, [box_command(witness, probe['audit_origin_mm'], probe['audit_size_mm']),
                               {'command': 'inspect.interference', 'params': {'bodies': names+[witness]}}],
                               out, case+'_'+probe['id'], paths)
        result = common.check_solidcraft_interference(raw[-1:], len(names)+1)
        probes.append({**probe, 'passed': result['passed'], 'interference': result, 'native_bodies_checked': names})
    support = support_geometry(spec, p, geometry)
    witness = 'S01_SupportWitness'
    if witness in names:
        raise ValueError('Support witness identity collides with scene body')
    targets = [support['carrier_body'], support['support_body']]
    raw = solidcraft_query(args, native, [box_command(witness, support['witness_origin_mm'], support['witness_size_mm'])]+
                           [{'command': 'inspect.interference', 'params': {'bodies': [target, witness]}} for target in targets],
                           out, case+'_support', paths)
    support = support_volumes(support, {target: support_intersection(result, target, witness) for target, result in zip(targets, raw[1:])})
    interfaces = model.check_interface_geometry(spec, p, geometry)
    if not interfaces:
        raise ValueError('Native scene interface checks required')
    return {'passed': interference['passed'] and support['passed'] and all(c['passed'] for c in interfaces+probes),
            'interfaces': interfaces, 'interference': interference, 'support': support,
            'access': {'passed': all(c['passed'] for c in probes), 'checks': probes},
            'construction': 'Direct shared operations, no FreeCAD or prebuilt K01 CAD input'}


def build(args):
    started = time.monotonic()
    source = Path(args.source).resolve()
    relative(source)
    model.SOURCE = source
    digest = common.robot_spec.digest(source)
    spec = model.load(source)
    pins = source_snapshot(spec, source)
    if pins[relative(source)] != digest:
        raise ValueError('Scene source changed while loading')
    common.verify_pins(pins)
    cases = [item['id'] if isinstance(item, dict) else item for item in model.cases(spec)]
    if len(cases) != 2 or set(cases) != CASES:
        raise ValueError('Exactly shelf/handover static scenes required')
    stem = 'kit-storage-s01-'+digest[:12]
    revision, index = stem, 1
    while any((ROOT/top/revision).exists() for top in ('cad/generated', 'exports/generated', 'renders')):
        index += 1
        revision = stem+'-r'+str(index)
    cad, out, render = [ROOT/top/revision for top in ('cad/generated', 'exports/generated', 'renders')]
    for folder in (cad, out, render):
        folder.mkdir(parents=True)
    results = []
    for identity in cases:
        common.verify_pins(pins)
        current = model.materialize(spec, identity)
        p = model.parameters(current)
        expanded = model.expanded(current, p)
        if expanded['joints']:
            raise ValueError('A static storage scene cannot introduce motion channels')
        paths = {'case': out/(identity+'.case.json')}
        write(paths['case'], {'id': identity, 'source': relative(source), 'source_sha256': digest, 'source_files_sha256': pins})
        print('Storage S01: '+identity+' ('+args.backend+')', flush=True)
        sc = fc = sc_checks = fc_checks = None
        if args.backend in {'both', 'solidcraft'}:
            paths.update(commands=out/(identity+'.commands.json'), solidcraft=cad/(identity+'.sc'),
                         solidcraft_measurements=out/(identity+'.solidcraft.json'))
            write(paths['commands'], {'source_sha256': digest, 'commands': model.solidcraft_commands(current, p)})
            command = [args.solidcraft_cli, 'run', str(paths['commands']), '--save', str(paths['solidcraft']),
                       '--json-out', str(paths['solidcraft_measurements']), '--quiet']
            if args.backend == 'both':
                paths['step'] = out/(identity+'.step')
                command += ['--out', str(paths['step'])]
            subprocess.run(command, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
            sc = common.measurements(json.loads(paths['solidcraft_measurements'].read_text()), expanded, backend='solidcraft')
            sc_checks = solidcraft_checks(args, current, p, paths['solidcraft'], out, identity, sc, paths)
        if args.backend in {'both', 'freecad'}:
            paths.update(freecad=cad/(identity+'.FCStd'), freecad_validation=out/(identity+'.freecad.json'))
            command = [args.freecad_python, str(ROOT/'scripts/build_kit_storage_freecad.py'), str(paths['case']),
                       str(paths['freecad']), str(paths['freecad_validation'])]
            if args.backend == 'both':
                command += ['--compare-step', str(paths['step'])]
            subprocess.run(command, check=True, cwd=ROOT, env=common.freecad_environment(args.freecad_python))
            fc_checks = json.loads(paths['freecad_validation'].read_text())
            if fc_checks['source_files_sha256'] != pins or fc_checks['source_sha256'] != digest or fc_checks['case'] != identity:
                raise ValueError('FreeCAD evidence refers to other inputs')
            fc = common.measurements(fc_checks, expanded, backend='freecad')
        cross = common.compare(sc, fc) if args.backend == 'both' else None
        passed = ((sc_checks is None or sc_checks['passed']) and (fc_checks is None or fc_checks['passed'])
                  and (cross is None or all(c['passed'] for c in cross)))
        result = {'id': identity, 'passed': passed, 'body_count': len(expanded['bodies']),
                  'interfaces': model.interfaces(current, p), 'solidcraft_checks': sc_checks,
                  'freecad_checks_passed': None if fc_checks is None else fc_checks['passed'],
                  'body_comparisons': cross, 'cross_cad_checked': args.backend == 'both' and passed,
                  'maximum_step_xor_mm3': max(c['xor_mm3'] for c in fc_checks['solidcraft_step_xor']) if cross is not None else None,
                  'files': {key: relative(path) for key, path in paths.items()},
                  'artifact_sha256': {key: common.robot_spec.digest(path) for key, path in paths.items()}}
        results.append(result)
        write(out/'cases-progress.json', results)
        common.verify_pins(pins)
        if not passed:
            raise AssertionError('Native storage scene failed: '+identity)
    renders = {}
    if args.backend in {'both', 'solidcraft'} and not args.no_render:
        for case in results:
            native = ROOT/case['files']['solidcraft']
            before = common.robot_spec.digest(native)
            image = render/(case['id']+'.png')
            subprocess.run([args.solidcraft_cli, 'snapshot', '--in', str(native), '--out', str(image),
                            '--width', '1300', '--height', '900', '--view', 'iso', '--no-grid', '--no-axes', '--quality', 'fine'],
                           check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
            if common.robot_spec.digest(native) != before:
                raise ValueError('Snapshot changed native input')
            renders[case['id']] = {'path': relative(image), 'sha256': common.robot_spec.digest(image), 'pixels': [1300, 900],
                                    'source': 'model', 'visually_reviewed': False}
    common.verify_pins(pins)
    for case in results:
        common.verify_artifacts({key: ROOT/path for key, path in case['files'].items()}, case['artifact_sha256'])
    report = {'format': FORMAT, 'source': relative(source), 'source_sha256': digest, 'source_files_sha256': pins,
              'revision': revision, 'backends': args.backend, 'passed': all(c['passed'] for c in results),
              'cross_cad_checked': args.backend == 'both' and all(c['passed'] for c in results), 'cases': results,
              'renders': renders, 'elapsed_s': time.monotonic()-started,
              'limitations': list(spec.get('limitations', []))+[
                  'Two static supported states; no transfer trajectory, rail robot, live grasp or hardware execution',
                  'Contact witnesses and offset access boxes verify only synthetic geometry, not load/stability/real-gripper suitability',
                  'FreeCAD saved presentation metadata checked; no FreeCAD GUI rendering qualification',
                  'Backend-only reports do not establish cross-CAD agreement']}
    write(out/'build-report.json', report)
    common.verify_pins(pins)
    write(ROOT/'cad/kit-storage-s01/shared-build-report.json', report)
    print('Storage S01 passed: '+relative(out/'build-report.json'), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['both', 'freecad', 'solidcraft'], default='both')
    parser.add_argument('--source', default=str(model.SOURCE))
    parser.add_argument('--no-render', action='store_true')
    tool_paths.add_tool_arguments(parser)
    args = parser.parse_args(argv)
    needed = common.required_tools(args.backend)
    tools = argparse.Namespace(**{name: getattr(args, name) for name in needed})
    tool_paths.resolve_tool_arguments(parser, tools, required=needed)
    for name in needed:
        setattr(args, name, getattr(tools, name))
    return build(args)


if __name__ == '__main__':
    main()
