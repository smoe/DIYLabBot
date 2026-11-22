"""Build a standalone browser walkthrough from checked native building/L01 models."""
import argparse
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import time

import export_building_walkthrough_freecad as mesh_export
import tool_paths
import walkthrough_world
from build_extraction_kit_station import freecad_environment

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.building-walkthrough-build/1'
TEMPLATE = ROOT/'scripts/building_walkthrough_viewer.html'
INTERACTION_SCRIPT = ROOT/'scripts/walkthrough_interaction.js'
SEMINAR_SCRIPT = ROOT/'scripts/seminar_projection.js'


def merge_pins(*collections):
    result = {}
    for pins in collections:
        for name, value in pins.items():
            if name in result and result[name] != value:
                raise ValueError('Conflicting walkthrough source pins: '+name)
            result[name] = value
    return result


def embed_html(template, payload):
    if template.count('__WALKTHROUGH_DATA__') != 1:
        raise ValueError('The walkthrough template needs exactly one data placeholder')
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    # A model label must not terminate the script element containing its JSON.
    data = data.replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    if template.count('__WALKTHROUGH_INTERACTION__') > 1:
        raise ValueError('Only one interaction-script placeholder is allowed')
    template = template.replace('__WALKTHROUGH_INTERACTION__', INTERACTION_SCRIPT.read_text(encoding='utf-8'))
    if '__WALKTHROUGH_SEMINAR__' in template:
        template = template.replace('__WALKTHROUGH_SEMINAR__', SEMINAR_SCRIPT.read_text(encoding='utf-8'))
    template = template.replace('__WALKTHROUGH_ROBOTS__', (ROOT/'scripts/templates/quintic_motion.js').read_text()+'\n'+(ROOT/'scripts/walkthrough_robots.js').read_text())
    template = template.replace('__WALKTHROUGH_MONITORS__', (ROOT/'scripts/monitor_frustum.js').read_text()+'\n'+(ROOT/'scripts/camera_monitor_wall.js').read_text())
    return template.replace('__WALKTHROUGH_DATA__', data)


def compile_monitor_overlay(program):
    """Derive the browser-only camera layer without modifying the native world."""
    import building_stack
    import monitor_camera_registry
    building = building_stack.load(ROOT/program['scene_sources']['building']['source'])
    interface = building_stack.interfaces(building, building_stack.parameters(building))
    wall = interface.get('monitor_wall')
    if wall is None:
        return None
    registry = monitor_camera_registry.compile(program, interface)
    level = next(row for row in interface['levels'] if row['id'] == wall['level_id'])
    return {
        'source_files_sha256': registry.pop('source_files_sha256'),
        'camera_wall': {**wall, **registry, 'mosaic_eye_z_bounds_mm': [level['z_mm'], level['clear_top_mm']]},
        'stop': {'id': 'camera-wall', 'label': 'Kamerawand · EG', 'scene': 'building',
                 'level_id': wall['level_id'], **wall['viewpoint']},
    }


def attach_monitor_overlay(program, overlay):
    if overlay is None:
        return program
    return {**program, 'camera_wall': overlay['camera_wall'],
            'stops': [*program['stops'], overlay['stop']],
            'source_files_sha256': merge_pins(program['source_files_sha256'], overlay['source_files_sha256'])}


def add_monitor_wall(program):
    return attach_monitor_overlay(program, compile_monitor_overlay(program))


def reports_from_program(program):
    sources = program['scene_sources']
    if set(sources) != {'building'} or 'equipment_source' not in program:
        raise ValueError('One building scene and its checked equipment source are required')
    sources = {**sources, 'lab': program['equipment_source']}
    return {name: mesh_export.project_path(ref['build_report']) for name, ref in sources.items()}


def ensure_reports(program, args):
    reports = reports_from_program(program)
    if args.building_report is not None:
        reports['building'] = mesh_export.project_path(args.building_report)
    if getattr(args, 'lab_report', None) is not None:
        reports['lab'] = mesh_export.project_path(args.lab_report)
    rebuild = bool(args.rebuild_building)
    try:
        mesh_export.checked_report(reports['building'], 'building')
    except (ValueError, FileNotFoundError):
        if args.no_rebuild:
            raise
        rebuild = True
    if rebuild:
        if args.no_rebuild:
            raise ValueError('--rebuild-building and --no-rebuild cannot be combined')
        source = program['scene_sources']['building']['source']
        import build_building_stack
        native = build_building_stack.build(argparse.Namespace(source=str(mesh_export.project_path(source)),
            backend='freecad', no_render=True, freecad_python=args.freecad_python))
        reports['building'] = ROOT/'exports/generated'/native['revision']/'build-report.json'
    # L01 is deliberately reused rather than rebuilding its unrelated gallery.
    checked = {scene: mesh_export.checked_report(path, scene) for scene, path in reports.items()}
    expected = {'building': program['scene_sources']['building'], 'lab': program['equipment_source']}
    for name, report in checked.items():
        if (report['source_sha256'] != expected[name]['source_sha256']
                or name == 'building' and report.get('source') != expected[name]['source']):
            raise ValueError('Native report does not match the requested walkthrough source: '+name)
    return reports, checked


def validate_bundle(bundle):
    if bundle.get('format') != mesh_export.FORMAT or set(bundle.get('scenes', {})) != {'building'}:
        raise ValueError('One checked furnished building mesh scene is required')
    mesh_export.verify_pins(bundle['source_files_sha256'])
    for scene, data in bundle['scenes'].items():
        groups = data.get('groups', [])
        if (not groups or len(groups) != data['native_body_count']
                or len({group['id'] for group in groups}) != len(groups)
                or sum(group['index_count'] for group in groups) != data['index_count']):
            raise ValueError('Incomplete native body surface coverage: '+scene)


def build(args):
    import building_walkthrough as model
    started = time.monotonic()
    program = model.compile(args.source)
    reports, checked = ensure_reports(program, args)
    # A rebuild can replace a checked report pointer; recompile against the
    # final source/proof set before pinning the browser artifact.
    program = model.compile(args.source)
    program['scene_sources']['building']['build_report'] = str(reports['building'].relative_to(ROOT))
    program['equipment_source']['build_report'] = str(reports['lab'].relative_to(ROOT))
    overlay = compile_monitor_overlay(program)
    world_inputs = merge_pins(program['source_files_sha256'],
        {str(path.relative_to(ROOT)): mesh_export.digest(path)
         for path in (Path(__file__), Path(walkthrough_world.__file__), Path(mesh_export.__file__), *reports.values())})
    browser_inputs = merge_pins(world_inputs, overlay['source_files_sha256'] if overlay else {},
        {str(path.relative_to(ROOT)): mesh_export.digest(path)
         for path in (TEMPLATE, INTERACTION_SCRIPT, SEMINAR_SCRIPT,
                      ROOT/'scripts/camera_monitor_wall.js', ROOT/'scripts/monitor_frustum.js')})
    key = hashlib.sha256(json.dumps(browser_inputs, sort_keys=True).encode()).hexdigest()
    stem = 'building-walkthrough-'+key[:12]
    output = ROOT/'exports/building-walkthrough'/stem if args.output_dir is None else mesh_export.project_path(args.output_dir)
    if args.output_dir is None:
        number, base = 1, output
        while output.exists():
            number += 1
            output = base.with_name(stem+'-r'+str(number))
    elif output.exists():
        raise FileExistsError('Walkthrough builds preserve existing artifacts: '+str(output))
    output.mkdir(parents=True)
    mesh_path = output/'native-mesh.json'
    subprocess.run([str(args.freecad_python), str(ROOT/'scripts/export_building_walkthrough_freecad.py'),
                    '--building-report', str(reports['building']), '--lab-report', str(reports['lab']),
                    '--out', str(mesh_path), '--building-deflection-mm', str(args.building_deflection_mm),
                    '--lab-deflection-mm', str(args.lab_deflection_mm),
                    '--angular-deflection-rad', str(args.angular_deflection_rad)], check=True, cwd=ROOT,
                   env=freecad_environment(args.freecad_python))
    bundle = json.loads(mesh_path.read_text(encoding='utf-8'))
    validate_bundle(bundle)
    world_pins = merge_pins(world_inputs, bundle['source_files_sha256'])
    pins = merge_pins(world_pins, browser_inputs)
    world = {**program, 'source_files_sha256': world_pins,
             'limitations': list(dict.fromkeys(program.get('limitations', [])+bundle.get('limitations', [])))}
    world['isolation']['body_ids'] = sorted(set(world['isolation']['body_ids']) |
        {group['id'] for group in bundle['scenes']['building']['groups']
         if group.get('laboratory_id') == world['isolation']['laboratory_id']})
    native_builds = {scene: {'report': str(reports[scene].relative_to(ROOT)),
        'report_sha256': mesh_export.digest(reports[scene]), 'revision': native['revision'],
        'source_sha256': native['source_sha256'], 'native_sha256': native['artifact_sha256']['freecad']}
        for scene, native in checked.items()}
    mesh_export.verify_pins(pins)
    world_report = walkthrough_world.write(output, world, native_builds)
    payload = {**attach_monitor_overlay(world, overlay), 'scenes': bundle['scenes'],
               'source_files_sha256': pins}
    index = output/'index.html'
    index.write_text(embed_html(TEMPLATE.read_text(encoding='utf-8'), payload), encoding='utf-8')
    manifest = output/'manifest.json'
    manifest.write_text(json.dumps({key: value for key, value in payload.items() if key != 'scenes'}, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    files = {'html': index, 'native_mesh': mesh_path, 'manifest': manifest,
             'world_report': world_report, 'world_manifest': output/walkthrough_world.FILES['manifest']}
    report = {'format': FORMAT, 'passed': True, 'revision': output.name,
              'source_files_sha256': pins,
              'files': {name: str(path.relative_to(ROOT)) for name, path in files.items()},
              'artifact_sha256': {name: mesh_export.digest(path) for name, path in files.items()},
              'native_builds': native_builds,
              'camera_overlay_source_files_sha256': overlay['source_files_sha256'] if overlay else {},
              'scenes': {scene: {key: data[key] for key in ('native_body_count', 'native_face_count', 'vertex_count', 'index_count',
                  'coordinate_frame', 'linear_tessellation_deflection_mm', 'maximum_float32_error_mm',
                  'angular_tessellation_deflection_rad', 'degenerate_triangles_omitted')} for scene, data in bundle['scenes'].items()},
              'browser_checked': False, 'elapsed_s': time.monotonic()-started,
              'scope': 'Checked source/native body coverage and standalone HTML export; browser rendering is a separate check',
              'limitations': payload['limitations']}
    mesh_export.verify_pins(pins)
    (output/'build-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print('Walkthrough: '+str(index), flush=True)
    print('Build report: '+str(output/'build-report.json'), flush=True)
    if args.serve:
        serve(output, args.port)
    return report


def serve(directory, port):
    def handler(*args, **kwargs):
        return SimpleHTTPRequestHandler(*args, directory=str(directory), **kwargs)
    with ThreadingHTTPServer(('127.0.0.1', port), handler) as server:
        print('Walkthrough server: http://127.0.0.1:'+str(server.server_port)+'/index.html', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=None, help='Shared walkthrough source (default: model/building-walkthrough.shared.json)')
    parser.add_argument('--building-report', default=None, help='Versioned checked FreeCAD building report (default: shared current report)')
    parser.add_argument('--lab-report', default=None, help='Versioned checked L01 report (default: shared current report)')
    parser.add_argument('--output-dir', default=None, help='New project-local output directory; existing outputs are preserved')
    parser.add_argument('--rebuild-building', action='store_true', help='Rebuild native FreeCAD even when the building proof is current')
    parser.add_argument('--no-rebuild', action='store_true', help='Require a current checked building cache instead of rebuilding stale inputs')
    parser.add_argument('--building-deflection-mm', type=float, default=3.)
    parser.add_argument('--lab-deflection-mm', type=float, default=1.)
    parser.add_argument('--angular-deflection-rad', type=float, default=.35)
    parser.add_argument('--serve', action='store_true', help='Serve the exported page on loopback after building')
    parser.add_argument('--port', type=int, default=8765, help='Loopback port for --serve (0 chooses a free port)')
    tool_paths.add_tool_arguments(parser, solidcraft=False)
    args = parser.parse_args(argv)
    tool_paths.resolve_tool_arguments(parser, args, required={'freecad_python'})
    return build(args)


if __name__ == '__main__':
    main()
