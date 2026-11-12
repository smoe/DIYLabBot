"""Build an uncalibrated floorplan in explicit synthetic display millimetres."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import time

import build_extraction_kit_station as common
import relative_floorplan as model
import tool_paths

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.relative-floorplan-build/1'
UNIT_NOTICE = 'Synthetic display mm only; no measured building dimensions, physical areas, clearances or routes'
write, relative = common.write, common.relative


def display_parameters(args):
    values = {name: getattr(args, name) for name in ('display_scale', 'display_height', 'display_thickness', 'display_floor_depth')}
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values.values()):
        raise ValueError('Explicit positive finite synthetic display parameters required')
    return values


def source_snapshot(spec, source):
    paths = [source, Path(__file__), ROOT/'scripts/build_relative_floorplan_freecad.py',
             ROOT/'scripts/build_extraction_kit_station.py', ROOT/'scripts/extraction_kit_station.py',
             ROOT/'scripts/build_tube_carrier_freecad.py', ROOT/'scripts/build_neutral_freecad.py',
             ROOT/'scripts/robot_cameras.py', ROOT/'scripts/freecad/solidcraftbot_freecad.py',
             ROOT/'scripts/freecad/persist_station_view.py', ROOT/'scripts/freecad/persist_view.py',
             ROOT/'scripts/tool_paths.py', *model.source_dependencies(spec)]
    result = {}
    for path in paths:
        path = Path(path).resolve()
        name = relative(path)
        # Public proof records contain public derived JSON and code only. The
        # photographed original is neither a runtime dependency nor a hash input.
        allowed = (name.startswith(('scripts/', 'model/', 'tests/fixtures/')) and path.suffix in {'.py', '.json'})
        if not allowed:
            raise ValueError('Non-public dependency cannot be included in the floorplan proof')
        result[name] = common.robot_spec.digest(path)
    return result


def modeled_opening_ids(spec):
    walls = {wall['id']: wall for wall in spec['walls']}
    return {opening['id'] for opening in spec['openings']
            if opening['kind'] in {'door', 'window'} and walls[opening['wall']]['kind'] == 'wall'}


def opening_probes(spec, p):
    probes = model.interfaces(spec, p)['opening_probes']
    if not isinstance(probes, list) or len({probe['id'] for probe in probes}) != len(probes):
        raise ValueError('Unique source-derived opening probes required')
    expected = modeled_opening_ids(spec)
    if {probe['id'] for probe in probes} != expected:
        raise ValueError('Opening proof coverage must match known openings on modeled walls')
    for probe in probes:
        points, z, height = probe['points_mm'], probe['offset_mm'], probe['depth_mm']
        if (not isinstance(probe['id'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', probe['id'])
                or not isinstance(probe['target_body'], str) or not probe['target_body']
                or probe.get('kind') != 'polygon_prism' or len(points) < 3
                or any(len(point) != 2 for point in points)
                or any(type(v) not in (int, float) or not math.isfinite(v) for point in points for v in point)
                or type(z) not in (int, float) or not math.isfinite(z)
                or type(height) not in (int, float) or not math.isfinite(height) or height <= 0):
            raise ValueError('Invalid synthetic display opening probe')
    return probes


def probe_commands(probe, name):
    return [
        {'command': 'sketch.create', 'params': {'name': name+'_Sketch', 'plane': 'XY', 'offset': probe['offset_mm']}},
        {'command': 'sketch.line', 'params': {'points': probe['points_mm'], 'closed': True, 'infer': False}},
        {'command': 'sketch.finish', 'params': {}},
        {'command': 'solid.extrude', 'params': {'name': name, 'body_name': name, 'operation': 'new', 'distance': probe['depth_mm']}},
        {'command': 'inspect.interference', 'params': {'bodies': [name, probe['target_body']]}}]


def solidcraft_openings(args, spec, p, native, out, geometry, paths):
    names = {body['body'] for body in geometry}
    original = common.robot_spec.digest(native)
    checks = []
    for probe in opening_probes(spec, p):
        name = 'FloorplanProbe_'+probe['id']
        if probe['target_body'] not in names or name in names:
            raise ValueError('Opening probe refers to a missing wall or conflicting body')
        script, result = out/(probe['id']+'.probe.commands.json'), out/(probe['id']+'.probe.result.json')
        commands = probe_commands(probe, name)
        write(script, {'commands': commands})
        subprocess.run([args.solidcraft_cli, 'run', str(script), '--in', str(native), '--results', '--quiet',
                        '--json-out', str(result)], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        if common.robot_spec.digest(native) != original:
            raise ValueError('Opening audit changed native floorplan')
        raw = json.loads(result.read_text())
        if not isinstance(raw, list) or len(raw) != len(commands):
            raise ValueError('Incomplete native opening-probe results')
        inspection = common.check_solidcraft_interference(raw[-1:], 2)
        checks.append({'id': probe['id'], 'target_body': probe['target_body'], 'passed': inspection['passed'],
                       'probe': probe, 'native_inspection': inspection,
                       'scope': 'Only the associated display wall cut; no whole-building access/clearance qualification'})
        paths[probe['id']+'_commands'], paths[probe['id']+'_result'] = script, result
    return checks


def comparison(actual, expected):
    checks = common.compare(actual, expected)
    return [{'body': c['body'], 'relative_volume_error': c['relative_volume_error'],
             'com_error_display_mm': c['com_error_mm'], 'bbox_error_display_mm': c['bbox_error_mm'],
             'passed': c['passed']} for c in checks]


def build(args):
    started = time.monotonic()
    display = display_parameters(args)
    source = Path(args.source).resolve()
    name = relative(source)
    if not name.startswith(('model/', 'tests/fixtures/')) or source.suffix != '.json':
        raise ValueError('A public derived model JSON or synthetic fixture is required')
    model.SOURCE = source
    digest = common.robot_spec.digest(source)
    spec = model.load(source)
    p = model.parameters(spec, display)
    expanded = model.expanded(spec, p)
    if not expanded['bodies']:
        raise ValueError('No classified geometry is available for a native display preview')
    semantics = model.interfaces(spec, p)
    cuts = [operation for operation in expanded['operations'] if operation['action'] == 'cut']
    expected_cuts = {'Opening_'+identity for identity in modeled_opening_ids(spec)}
    if len(cuts) != len(expected_cuts) or {operation['id'] for operation in cuts} != expected_cuts:
        raise ValueError('Only known source openings may create native wall cuts')
    if expanded['joints']:
        raise ValueError('A relative floorplan preview is static')
    pins = source_snapshot(spec, source)
    if pins[name] != digest:
        raise ValueError('Derived source changed while loading')
    common.verify_pins(pins)
    stem = source.stem.replace('.shared', '')+'-display-'+digest[:12]
    revision, number = stem, 1
    while any((ROOT/top/revision).exists() for top in ('cad/generated', 'exports/generated', 'renders')):
        number += 1
        revision = stem+'-r'+str(number)
    cad, out, render = [ROOT/top/revision for top in ('cad/generated', 'exports/generated', 'renders')]
    for folder in (cad, out, render):
        folder.mkdir(parents=True)
    paths = {'case': out/'overview.case.json'}
    write(paths['case'], {'source': name, 'source_sha256': digest, 'source_files_sha256': pins, 'display_parameters': display})
    sc = fc = sc_checks = fc_checks = None
    print('Relative floorplan: '+args.backend+'; '+UNIT_NOTICE, flush=True)
    if args.backend in {'both', 'solidcraft'}:
        paths.update(commands=out/'overview.commands.json', solidcraft=cad/'overview.sc', solidcraft_measurements=out/'overview.solidcraft.json')
        write(paths['commands'], {'source_sha256': digest, 'coordinate_meaning': UNIT_NOTICE,
                                 'commands': model.solidcraft_commands(spec, p)})
        command = [args.solidcraft_cli, 'run', str(paths['commands']), '--save', str(paths['solidcraft']),
                   '--json-out', str(paths['solidcraft_measurements']), '--quiet']
        if args.backend == 'both':
            paths['step'] = out/'overview.step'
            command += ['--out', str(paths['step'])]
        subprocess.run(command, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        sc = common.measurements(json.loads(paths['solidcraft_measurements'].read_text()), expanded, backend='solidcraft')
        sc_checks = solidcraft_openings(args, spec, p, paths['solidcraft'], out, sc, paths)
    if args.backend in {'both', 'freecad'}:
        paths.update(freecad=cad/'overview.FCStd', freecad_validation=out/'overview.freecad.json')
        command = [args.freecad_python, str(ROOT/'scripts/build_relative_floorplan_freecad.py'),
                   str(paths['case']), str(paths['freecad']), str(paths['freecad_validation'])]
        if args.backend == 'both':
            command += ['--compare-step', str(paths['step'])]
        subprocess.run(command, check=True, cwd=ROOT, env=common.freecad_environment(args.freecad_python))
        fc_checks = json.loads(paths['freecad_validation'].read_text())
        if (fc_checks['source_sha256'] != digest or fc_checks['source_files_sha256'] != pins
                or fc_checks['display_parameters'] != display):
            raise ValueError('Native FreeCAD proof belongs to other derived inputs')
        fc = common.measurements(fc_checks, expanded, backend='freecad')
    cross = comparison(sc, fc) if args.backend == 'both' else None
    passed = ((sc_checks is None or all(c['passed'] for c in sc_checks)) and (fc_checks is None or fc_checks['passed'])
              and (cross is None or all(c['passed'] for c in cross)))
    if not passed:
        write(out/'failed-checks.json', {'passed': False, 'solidcraft_openings': sc_checks, 'freecad': fc_checks, 'comparison': cross})
        raise AssertionError('Native synthetic display geometry/opening checks failed')
    artifacts = {key: common.robot_spec.digest(path) for key, path in paths.items()}
    renders = {}
    if args.backend in {'both', 'solidcraft'} and not args.no_render:
        image = render/'overview.png'
        subprocess.run([args.solidcraft_cli, 'snapshot', '--in', str(paths['solidcraft']), '--out', str(image),
                        '--width', '1300', '--height', '900', '--view', 'iso', '--no-grid', '--no-axes', '--quality', 'fine'],
                       check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        renders['overview'] = {'path': relative(image), 'sha256': common.robot_spec.digest(image), 'pixels': [1300, 900], 'visually_reviewed': False}
    common.verify_pins(pins)
    common.verify_artifacts(paths, artifacts)
    report = {'format': FORMAT, 'source': name, 'source_sha256': digest, 'source_files_sha256': pins,
              'revision': revision, 'backends': args.backend, 'passed': passed, 'cross_cad_checked': args.backend == 'both',
              'metric_scale_known': False, 'coordinate_meaning': UNIT_NOTICE,
              'native_units': {'length': 'synthetic display mm', 'volume': 'synthetic display mm^3'},
              'display_parameters': display, 'body_count': len(expanded['bodies']),
              'representation': {
                  'declared_walls': len(spec['walls']), 'declared_areas': len(spec['areas']),
                  'declared_wall_kinds': {kind: sum(w['kind'] == kind for w in spec['walls'])
                                          for kind in ('wall', 'open_boundary', 'unknown')},
                  'constructed_wall_bodies': sum(b['role'] == 'relative_wall_display' for b in expanded['bodies']),
                  'constructed_floor_bodies': sum(b['role'] == 'relative_area_display' for b in expanded['bodies']),
                  'unmodeled_openings': semantics['unmodeled_openings']},
              'solidcraft_opening_checks': sc_checks, 'freecad_checks_passed': None if fc_checks is None else fc_checks['passed'],
              'body_comparisons': cross, 'maximum_step_xor_display_mm3': (max(c['xor_mm3'] for c in fc_checks['solidcraft_step_xor']) if cross is not None else None),
              'files': {key: relative(path) for key, path in paths.items()}, 'artifact_sha256': artifacts,
              'renders': renders, 'elapsed_s': time.monotonic()-started,
              'interference': {'checked': False, 'zero_interference_claimed': False,
                               'junction_overlaps': 'Display wall strips meeting at shared rigid nodes may overlap intentionally'},
              'limitations': ['Uncalibrated relative XY; no real building heights, thicknesses, lengths or areas inferred',
                              'Open/unknown boundaries and void/unknown area floors are omitted from 3D; omission is not a surveyed building fact',
                              'Door/window heights and wall/floor thicknesses are synthetic display assumptions only',
                              'Opening probes cover their associated wall only; no global access, load, route or safety qualification',
                              'Wall-junction overlaps are an allowed schematic representation, not a collision-free construction',
                              'Original photograph is not a build input, copied asset or source-hash dependency',
                              'STEP is used only for optional comparison; each backend constructs directly from the derived source']}
    write(out/'build-report.json', report)
    common.verify_pins(pins)
    write(ROOT/'cad/relative-floorplan'/source.stem/'shared-build-report.json', report)
    print('Relative display preview passed: '+relative(out/'build-report.json'), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=str(model.SOURCE))
    parser.add_argument('--display-scale', type=float, required=True, help='Explicit synthetic display mm per relative unit; not calibration')
    parser.add_argument('--display-height', type=float, default=model.DISPLAY_DEFAULTS['display_height'])
    parser.add_argument('--display-thickness', type=float, default=model.DISPLAY_DEFAULTS['display_thickness'])
    parser.add_argument('--display-floor-depth', type=float, default=model.DISPLAY_DEFAULTS['display_floor_depth'])
    parser.add_argument('--backend', choices=['both', 'freecad', 'solidcraft'], default='both')
    parser.add_argument('--no-render', action='store_true')
    tool_paths.add_tool_arguments(parser)
    args = parser.parse_args(argv)
    try:
        display_parameters(args)
    except ValueError as error:
        parser.error(str(error))
    needed = common.required_tools(args.backend)
    tools = argparse.Namespace(**{name: getattr(args, name) for name in needed})
    tool_paths.resolve_tool_arguments(parser, tools, required=needed)
    for name in needed:
        setattr(args, name, getattr(tools, name))
    return build(args)


if __name__ == '__main__':
    main()
