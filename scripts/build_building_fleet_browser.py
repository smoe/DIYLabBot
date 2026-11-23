#!/usr/bin/env python3
"""Package the unchanged BF01 engine and checked static inputs for a browser worker.

This is a portable source/data bundle, never an action recording. It retains
the original bytes required by the existing source, mesh and cache checks.
"""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from types import SimpleNamespace
import zipfile

import building_fleet_model as model
import building_fleet_patrol_cache as static_cache
from building_fleet_resources import ResourceCatalog
from building_fleet_routes import Navigation
import export_building_walkthrough_freecad as native
import run_building_fleet_patrol as local

ROOT = model.ROOT
BROWSER_SOURCE = ROOT / 'model/building-fleet-browser.shared.json'
BOOTSTRAP = 'scripts/building_fleet_browser_runtime.py'
WORKER = 'scripts/building_fleet_browser_worker.mjs'
TRANSPORT = 'scripts/building_fleet_browser_transport.js'
FORMAT = 'solidcraftbot.building-fleet-browser-bundle/1'
RECORDING_FORMATS = frozenset({
    'solidcraftbot.building-fleet-program/1',
    'solidcraftbot.building-fleet-live-snapshot/1',
    'solidcraftbot.building-fleet-runtime-failure/1',
    'solidcraftbot.building-fleet-own-input-evidence/2'})
RECORDING_NAMES = frozenset({'program.json', 'partial-program.json', 'commands.jsonl',
    'runtime-source-start.json', 'runtime-failure.json', 'browser-observed-state.json',
    'own-controller-observations.jsonl.gz'})
HEX = re.compile(r'[0-9a-f]{64}\Z')
PYTHON_CORE_FILES = frozenset({'pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm',
                              'python_stdlib.zip', 'pyodide-lock.json'})


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode()


def archive_name(value):
    """A plain project-relative path cannot escape the worker filesystem."""
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Plain project-relative archive path required')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('Archive path cannot escape its project root')
    if path.name in RECORDING_NAMES or path.name.endswith('.jsonl'):
        raise ValueError('Action recordings cannot enter a live runtime bundle')
    return value


class FileSet:
    """Hash every actual input and fence it again after deterministic packing."""
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.files = {}

    def add(self, path, expected=None):
        path = Path(path)
        path = path if path.is_absolute() else self.root / path
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symbolic runtime input: ' + str(path))
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError('Runtime input must stay inside the project')
        name = archive_name(resolved.relative_to(self.root).as_posix())
        raw = resolved.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected is not None and (not isinstance(expected, str) or
                                    not HEX.fullmatch(expected) or digest != expected):
            raise ValueError('Stale runtime input: ' + name)
        row = {'sha256': digest, 'bytes': len(raw)}
        if name in self.files and self.files[name] != row:
            raise ValueError('Input changed while collecting the bundle: ' + name)
        self.files[name] = row
        return name

    def pins(self, pins):
        if type(pins) is not dict or not pins:
            raise ValueError('Nonempty source pin mapping required')
        for name, digest in pins.items():
            self.add(archive_name(name), digest)

    def read(self, path):
        name = self.add(path)
        value = model.read_json(self.root / name)
        if isinstance(value, dict) and value.get('format') in RECORDING_FORMATS:
            raise ValueError('A live bundle may contain static inputs only')
        return value

    def verify(self):
        for name, row in tuple(self.files.items()):
            self.add(name, row['sha256'])


def load_browser_source(path=BROWSER_SOURCE):
    value = model.read_json(path)
    if (type(value) is not dict or set(value) !=
            {'format', 'id', 'sources', 'runtime', 'session', 'qualification'}
            or value['format'] != 'solidcraftbot.building-fleet-browser/1'
            or value['id'] != 'BF01-Browser'
            or set(value['sources']) not in ({'patrol'}, {'patrol', 'python_core'})):
        raise ValueError('Explicit browser fleet source required')
    if value['sources']['patrol'] != local.artifact(local.PROFILE):
        raise ValueError('Browser source must pin the current patrol profile')
    runtime = value['runtime']
    fields = {'engine', 'version', 'loader_module_url', 'execution', 'pacing', 'static_route_witnesses'}
    if 'python_core' in value['sources']:
        fields.add('delivery')
        if runtime.get('delivery') != 'same_origin_pinned_core':
            raise ValueError('Explicit unchanged same-origin Python core delivery required')
    if (set(runtime) != fields
            or runtime['engine'] != 'pyodide' or runtime['execution'] != 'module_web_worker'
            or runtime['pacing'] != 'source_step_without_wall_clock_catchup'
            or runtime['static_route_witnesses'] !=
                'original_pinned_metadata_for_bit_identical_geometry'
            or not re.fullmatch(r'\d+\.\d+\.\d+', runtime['version'])
            or runtime['loader_module_url'] !=
                'https://cdn.jsdelivr.net/pyodide/v' + runtime['version'] + '/full/pyodide.mjs'):
        raise ValueError('Supported source-declared module-worker runtime required')
    if value['session'] != {'scope': 'independent_live_session_per_page',
                           'start': 'new_patrol_world', 'recording_fallback': False}:
        raise ValueError('A browser page must start its own live world without recording fallback')
    if value['qualification'] != {'simulation_only': True, 'empty_vehicles': True,
            'network_video_implemented': False, 'full_mission_coverage_verified': False,
            'native_full_program_verified': False, 'independent_export_verified': False,
            'hardware_or_real_safety_qualified': False}:
        raise ValueError('A portable runtime cannot claim completed-run qualification')
    return value


def pinned_artifacts(files, report):
    files.pins(report['source_files_sha256'])
    names, hashes = report.get('files', {}), report.get('artifact_sha256', {})
    if set(names) != set(hashes):
        raise ValueError('Complete report artifact hashes required')
    for name, digest in hashes.items():
        files.add(names[name], digest)


def collect(inputs, *, root=ROOT):
    """Validate static interfaces without compiling a mission or native CAD."""
    if Path(root).resolve() != ROOT.resolve():
        raise ValueError('The runtime uses the checked project root')
    files = FileSet(root)
    source = model.load()
    profile = local.load_profile(ROOT / inputs['profile'])
    browser_source = load_browser_source(ROOT / inputs['browser_source'])
    files.add(inputs['profile'])
    files.add(inputs['browser_source'])
    if 'python_core' in browser_source['sources']:
        ref = browser_source['sources']['python_core']
        files.add(ref['path'], ref['sha256'])
    files.pins(model.source_pins(source))
    files.pins(model.protected_pins())
    world_path = ROOT / inputs['walkthrough_export'] / 'world-build-report.json'
    world = files.read(world_path)
    if world.get('format') != 'solidcraftbot.building-walkthrough-world/1' or world.get('passed') is not True:
        raise ValueError('Successful checked static world required')
    pinned_artifacts(files, world)
    camera = files.read(inputs['camera_report'])
    from export_building_fleet_vehicle_freecad import checked_camera_report
    checked_camera_report(ROOT / inputs['camera_report'])
    pinned_artifacts(files, camera)
    mesh = files.read(inputs['vehicle_mesh'])
    if (mesh.get('format') != 'solidcraftbot.building-fleet-vehicle-mesh/1'
            or mesh['camera_report'] != local.artifact(inputs['camera_report'])):
        raise ValueError('Current physical vehicle mesh required')
    files.pins(mesh['source_files_sha256'])
    probe = Navigation.__new__(Navigation)
    probe.config = source
    probe.mesh = SimpleNamespace(world_report_path=world_path.resolve())
    nav_report = files.read(ROOT / inputs['navigation_cache'] / 'cache-report.json')
    if (nav_report.get('format') != 'solidcraftbot.building-fleet-navigation-cache/1'
            or nav_report.get('source_files_sha256') != probe._cache_pins()
            or nav_report.get('walkthrough_build_report_sha256') != model.digest(world_path)
            or nav_report.get('qualification') != {'curve_qualified': False,
                'fleet_compiled': False, 'navigation_qualified': False}):
        raise ValueError('Current static navigation cache required')
    files.pins(nav_report['source_files_sha256'])
    files.add(ROOT / inputs['navigation_cache'] / nav_report['file'], nav_report['artifact_sha256'])
    resource_report = files.read(ROOT / inputs['resource_cache'] / 'cache-report.json')
    resource_probe = ResourceCatalog.__new__(ResourceCatalog)
    resource_probe.nav = probe
    if (resource_report.get('format') not in ('solidcraftbot.building-fleet-resource-cache/1',
                                             'solidcraftbot.building-fleet-resource-cache/2')
            or (resource_report['format'].endswith('/2') and
                resource_report.get('path_validation') != 'complete_original_path_construction')
            or resource_report.get('source_files_sha256') != resource_probe._cache_pins()):
        raise ValueError('Current static resource cache required')
    files.pins(resource_report['source_files_sha256'])
    files.add(ROOT / inputs['resource_cache'] / resource_report['file'], resource_report['artifact_sha256'])
    graph_report = files.read(inputs['graph_cache_report'])
    if 'data_equivalence' in graph_report:
        ref = graph_report['data_equivalence']
        files.add(ref['path'], ref['sha256'])
        equivalence = files.read(ref['path'])
        checker = equivalence['checker']
        files.add(checker['path'], checker['sha256'])
    required = static_cache._mandatory_pins(probe)
    pins = graph_report.get('source_files_sha256_start')
    if (graph_report.get('format') != 'solidcraftbot.building-fleet-static-preparation/1'
            or graph_report.get('passed') is not True or graph_report.get('engine_model_time_s') != 0
            or pins != graph_report.get('source_files_sha256_end')):
        raise ValueError('A static graph preparation, never a mission run, is required')
    static_cache._verify_pins(pins, required)
    files.pins(pins)
    graph_ref = graph_report['route_graph']
    files.add(graph_ref['path'], graph_ref['sha256'])
    graph = files.read(graph_ref['path'])
    if (graph.get('format') != 'solidcraftbot.building-fleet-route-graph-cache/1'
            or graph.get('source_files_sha256') != pins
            or graph.get('sealed') is not True
            or graph.get('qualification') != static_cache.QUALIFICATION
            or graph.get('route_bank_sha256') != resource_report['route_bank_sha256']
            or ResourceCatalog.route_bank_hash(graph['routes']) != resource_report['route_bank_sha256']):
        raise ValueError('The complete static route bank must match its checked resource cache')
    for key in ('world_report', 'navigation_input', 'resource_input'):
        ref = graph[key]
        files.add(ref['path'], ref['sha256'])
    # All project modules imported by the real bootstrap are original files.
    # Include dynamic constructor dependencies explicitly, without executing a run.
    for name in ('building_fleet_browser_runtime', 'building_fleet_patrol',
                 'building_fleet_browser_navigation',
                 'building_fleet_geometry_checks', 'building_fleet_port_paths',
                 'building_fleet_zones', 'building_fleet_floor'):
        importlib.import_module(name)
    for module in tuple(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if path and Path(path).is_file() and Path(path).resolve().is_relative_to(ROOT.resolve()):
            relative = Path(path).resolve().relative_to(ROOT.resolve())
            if relative.parts[0] in ('scripts', 'ros2_ws') and relative.suffix == '.py':
                files.add(Path(path).resolve())
    for name in (BOOTSTRAP, WORKER, TRANSPORT,
                 'scripts/building_fleet_browser_navigation.py',
                 'scripts/build_building_fleet_browser.py'):
        files.add(name)
    files.verify()
    return files, browser_source, profile


def collect_python_core(browser_source, directory):
    """Keep unchanged official runtime bytes outside the simulation ZIP."""
    ref = browser_source['sources']['python_core']
    descriptor = model.read_json(model.resolve_pin(ref))
    if (descriptor.get('format') != 'solidcraftbot.building-fleet-python-core/1' or
            descriptor.get('version') != browser_source['runtime']['version'] or
            not PYTHON_CORE_FILES <= set(descriptor.get('files', {}))):
        raise ValueError('Version-matched pinned original Python runtime files required')
    if 'project_notice' in descriptor and hashlib.sha256(descriptor['project_notice'].encode()).hexdigest() != descriptor['files'].get('NOTICE', {}).get('sha256'):
        raise ValueError('The project source-availability notice differs from its leading text')
    originals = FileSet()
    directory = local.project_path(directory)
    for name, row in descriptor['files'].items():
        archive_name(name)
        path = directory / name
        originals.add(path, row['sha256'])
        if path.stat().st_size != row['bytes']:
            raise ValueError('Original Python runtime file size changed: ' + name)
    return {'source': copy.deepcopy(ref), 'files': copy.deepcopy(descriptor['files']),
        'directory': 'python/' + descriptor['version'] + '-' + ref['sha256'][:16],
        'originals': originals, 'input_directory': directory}


def pack(files, browser_source, inputs, output, *, python_core=None):
    """Write an immutable deterministic archive and independently hashed manifest."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    archive = output / 'runtime.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for name in sorted(files.files):
            info = zipfile.ZipInfo(archive_name(name), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(info, (files.root / name).read_bytes(), compresslevel=6)
    files.verify()
    manifest = {'format': FORMAT, 'root_dir': '/project',
        'bootstrap_path': BOOTSTRAP, 'inputs': copy.deepcopy(inputs),
        'runtime': copy.deepcopy(browser_source['runtime']),
        'session': copy.deepcopy(browser_source['session']),
        'browser_config': {'path': inputs['browser_source'],
            'sha256': files.files[inputs['browser_source']]['sha256']},
        'files': dict(sorted(files.files.items())),
        'archive': {'path': archive.name, 'sha256': model.digest(archive),
                    'bytes': archive.stat().st_size},
        'qualification': copy.deepcopy(browser_source['qualification']),
        'scope': 'Original engine sources and checked static geometry/cache inputs only; a new independent live world starts per page, without prior mission, snapshot, action journal or recording fallback.'}
    if python_core is not None:
        manifest['python_core'] = {key: copy.deepcopy(python_core[key])
                                   for key in ('source', 'files', 'directory')}
        for name in python_core['files']:
            target = output / python_core['directory'] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(python_core['input_directory'] / name, target)
        python_core['originals'].verify()
    (output / 'runtime-manifest.json').write_bytes(json_bytes(manifest))
    return manifest


def build(inputs, output, *, bundle_only=False, python_core_dir=None):
    output = local.project_path(output, output=True)
    files, browser_source, profile = collect(inputs)
    python_core = None
    if 'python_core' in browser_source['sources']:
        if python_core_dir is None:
            raise ValueError('Supply the pinned official Python core directory')
        python_core = collect_python_core(browser_source, python_core_dir)
    elif python_core_dir is not None:
        raise ValueError('Python runtime delivery must be declared in the leading browser source')
    manifest = pack(files, browser_source, inputs, output, python_core=python_core)
    manifest_ref = local.artifact(output / 'runtime-manifest.json')
    worker = {'module_url': 'building_fleet_browser_worker.mjs?sha256=' + files.files[WORKER]['sha256'],
        'manifest': {'url': 'runtime-manifest.json?sha256=' + manifest_ref['sha256'],
                     'sha256': manifest_ref['sha256']},
        'bundle': {'url': 'runtime.zip?sha256=' + manifest['archive']['sha256'],
                   'sha256': manifest['archive']['sha256']}}
    presentation_pins = {}
    for source, name in ((WORKER, 'building_fleet_browser_worker.mjs'),
                         (TRANSPORT, 'building_fleet_browser_transport.js')):
        shutil.copyfile(ROOT / source, output / name)
    if not bundle_only:
        source = model.load()
        args = SimpleNamespace(**inputs)
        local_report = local.build_page(source, profile, args, output)
        presentation_pins = local_report['source_files_sha256']
        page = (output / 'index.html').read_text()
        pattern = r'(<script id="building-fleet-data" type="application/json">)([^<]*)(</script>)'
        match = re.search(pattern, page)
        if match is None:
            raise ValueError('Current active viewer payload is missing')
        payload = json.loads(match.group(2))
        if any(name in payload for name in ('program_gzip_base64', 'experimental_preview')):
            raise ValueError('Live browser publication cannot contain a recorded program')
        payload['live'] = {'worker': worker,
            'poll_interval_ms': payload['live']['poll_interval_ms'],
            'targets': payload['live']['targets']}
        encoded = json.dumps(payload, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
        page = page[:match.start(2)] + encoded + page[match.end(2):]
        script_url = 'building_fleet_browser_transport.js?sha256=' + files.files[TRANSPORT]['sha256']
        page = page.replace('</head>', '<script src="' + script_url + '"></script></head>')
        (output / 'index.html').write_text(page)
        # The final browser document has a separate exact build receipt.
        # Do not retain a local-HTTP HTML hash under the public build name.
        (output / 'build-report.json').unlink()
    artifacts = {p.relative_to(output).as_posix(): {'sha256': model.digest(p), 'bytes': p.stat().st_size}
                 for p in output.rglob('*') if p.is_file()}
    report = {'format': 'solidcraftbot.building-fleet-browser-build/1', 'passed': True,
        'source_files_sha256': {**{name: row['sha256'] for name, row in files.files.items()},
                               **presentation_pins},
        'inputs': copy.deepcopy(inputs), 'runtime_manifest': manifest_ref,
        'runtime': copy.deepcopy(manifest['runtime']), 'session': copy.deepcopy(manifest['session']),
        'qualification': copy.deepcopy(manifest['qualification']), 'bundle_only': bundle_only,
        'files': artifacts, 'uncompressed_runtime_bytes': sum(row['bytes'] for row in files.files.values()),
        'browser_checked': False, 'scope': manifest['scope']}
    if python_core is not None:
        report['source_files_sha256'].update({name: row['sha256']
            for name, row in python_core['originals'].files.items()})
    (output / 'browser-build-report.json').write_bytes(json_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('walkthrough-export', 'camera-report', 'vehicle-mesh',
                 'navigation-cache', 'resource-cache', 'graph-cache-report', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--profile', default='model/building-fleet-patrol.shared.json')
    parser.add_argument('--browser-source', default='model/building-fleet-browser.shared.json')
    parser.add_argument('--bundle-only', action='store_true')
    parser.add_argument('--python-core-dir', help='Original official core files declared by the browser source')
    args = parser.parse_args(argv)
    inputs = {name: (ROOT / getattr(args, name)).resolve().relative_to(ROOT.resolve()).as_posix()
              for name in ('walkthrough_export', 'camera_report', 'vehicle_mesh',
                           'navigation_cache', 'resource_cache', 'graph_cache_report',
                           'profile', 'browser_source')}
    result = build(inputs, args.output_dir, bundle_only=args.bundle_only,
                   python_core_dir=args.python_core_dir)
    print(json.dumps({'passed': result['passed'], 'files': len(result['source_files_sha256']),
        'runtime_archive_bytes': result['files']['runtime.zip']['bytes'],
        'uncompressed_runtime_bytes': result['uncompressed_runtime_bytes']}), flush=True)


if __name__ == '__main__':
    main()
