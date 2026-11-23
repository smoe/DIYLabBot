"""JSON boundary for a fresh BF01 engine inside a browser Python worker.

The browser supplies exact source-pinned project files in its private file
system. This module neither starts servers/threads nor loads a recording.
Physics, observations, motion, resources and recruitment remain in the same
PatrolWorldRunner used by the local executable.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

import building_fleet_model as model


INPUTS = frozenset({'profile', 'navigation_cache', 'graph_cache_report',
    'resource_cache', 'walkthrough_export', 'camera_report', 'vehicle_mesh'})
OPTIONAL = frozenset({'browser_source', 'browser_config_sha256'})


def _decode(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('Duplicate JSON field: '+key)
            result[key] = item
        return result
    if not isinstance(value, str):
        raise ValueError('A JSON string is required at the browser boundary')
    result = json.loads(value, object_pairs_hook=pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+token)))
    if type(result) is not dict:
        raise ValueError('A JSON object is required at the browser boundary')
    return result


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _path(value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('A relative bundled project path is required')
    root = model.ROOT.resolve()
    path = (root/value).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Bundled paths must remain inside the project')
    return path


def _configuration(config):
    required = INPUTS | {'root', 'source_files_sha256'}
    if not required <= set(config) or set(config)-required-OPTIONAL:
        raise ValueError('Closed browser engine configuration required')
    if config['root'] != str(model.ROOT.resolve()):
        raise ValueError('Browser project root differs from the imported engine')
    paths = {name: _path(config[name]) for name in INPUTS}
    paths['browser_source'] = _path(config.get('browser_source', 'model/building-fleet-browser.shared.json'))
    pins = config['source_files_sha256']
    if not isinstance(pins, dict) or not pins:
        raise ValueError('The verified bundle source closure is required')
    mandatory = {'scripts/building_fleet_browser_runtime.py', 'scripts/building_fleet_patrol.py',
                 'scripts/building_fleet_browser_navigation.py',
                 'scripts/building_fleet_browser_worker.mjs', 'scripts/building_fleet_browser_transport.js',
                 'model/building-fleet-browser.shared.json', 'model/building-fleet-patrol.shared.json'}
    if not mandatory <= set(pins):
        raise ValueError('Browser adapters and leading sources must be pinned')
    # Verify the complete supplied closure with the same source-pin primitive.
    # This also checks native CAD bytes; browser files are never stubbed.
    for path, digest in pins.items():
        _path(path)
        model.resolve_pin({'path': path, 'sha256': digest})
    browser = model.read_json(paths['browser_source'])
    if 'python_core' in browser.get('sources', {}):
        ref = browser['sources']['python_core']
        if pins.get(ref['path']) != ref['sha256']:
            raise ValueError('The original Python runtime descriptor must be in the verified closure')
        core = model.read_json(model.resolve_pin(ref))
        if (browser.get('runtime', {}).get('delivery') != 'same_origin_pinned_core' or
                core.get('format') != 'solidcraftbot.building-fleet-python-core/1' or
                core.get('version') != browser['runtime'].get('version')):
            raise ValueError('Source-bound original same-origin Python runtime required')
    elif browser.get('runtime', {}).get('delivery') is not None:
        raise ValueError('Python runtime delivery must have a pinned original descriptor')
    if (browser.get('format') != 'solidcraftbot.building-fleet-browser/1' or
            browser.get('session') != {'scope': 'independent_live_session_per_page',
                'start': 'new_patrol_world', 'recording_fallback': False} or
            browser.get('runtime', {}).get('engine') != 'pyodide' or
            browser.get('runtime', {}).get('execution') != 'module_web_worker' or
            browser.get('runtime', {}).get('static_route_witnesses') !=
                'original_pinned_metadata_for_bit_identical_geometry' or
            browser.get('runtime', {}).get('pacing') != 'source_step_without_wall_clock_catchup'):
        raise ValueError('A fresh independent browser-worker world without recording fallback is required')
    if model.resolve_pin(browser['sources']['patrol']) != paths['profile']:
        raise ValueError('Browser profile differs from its leading pinned source')
    profile = model.read_json(paths['profile'])
    source = model.load(model.resolve_pin(profile['sources']['fleet']))
    if (profile.get('format') != 'solidcraftbot.building-fleet-patrol/1' or
            profile.get('patrol') != {'termination': 'explicit_stop',
                'startup': 'first_received_camera_frames', 'targets': '/missions/targets',
                'selection': 'oldest_received_visit'} or
            profile.get('recruitment') != {'selection': 'lowest_feasible_route_eta',
                'diversion': 'observed_stationary_boundary',
                'pickup_delivery': 'empty_inspection_visits',
                'acknowledgement': 'received_mission_and_completion'}):
        raise ValueError('Unsupported continuous empty-patrol policy')
    for qualification in (browser.get('qualification', {}), profile.get('qualification', {})):
        if (qualification.get('simulation_only') is not True or
                qualification.get('empty_vehicles') is not True or
                any(value is not False for key, value in qualification.items()
                    if key not in ('simulation_only', 'empty_vehicles'))):
            raise ValueError('Browser simulation cannot assert physical or complete-run qualification')
    return paths, source, profile, copy.deepcopy(pins)


def _make_engine(paths, source, profile, progress):
    """Restore existing static caches and instantiate the unchanged core."""
    from building_fleet_browser_navigation import BrowserNavigation
    from building_fleet_patrol_cache import prepare_cached
    from building_fleet_geometry_checks import GeometryChecks
    from building_fleet_patrol import PatrolWorldRunner
    from export_building_fleet_vehicle_freecad import checked_camera_report

    progress({'phase': 'checking_camera_geometry'})
    checked_camera_report(paths['camera_report'])
    vehicle = model.read_json(paths['vehicle_mesh'])
    if (vehicle.get('format') != 'solidcraftbot.building-fleet-vehicle-mesh/1' or
            vehicle.get('camera_report') != {'path': paths['camera_report'].relative_to(model.ROOT).as_posix(),
                                            'sha256': model.digest(paths['camera_report'])}):
        raise ValueError('Source-matched native vehicle mesh required')
    for path, digest in vehicle['source_files_sha256'].items():
        model.resolve_pin({'path': path, 'sha256': digest})
    progress({'phase': 'checking_navigation'})
    nav = BrowserNavigation.from_cache(source, paths['walkthrough_export'], paths['navigation_cache'])
    nav.bind_source_metadata(paths['graph_cache_report'])
    prepared = prepare_cached(source, nav, paths['graph_cache_report'], paths['resource_cache'],
                              progress=progress)
    progress({'phase': 'static_route_witnesses_bound',
              'browser_static_route_witnesses': nav.browser_metadata_provenance()})
    return PatrolWorldRunner(source, nav, *prepared, profile, progress=progress,
        geometry_checker=GeometryChecks(source, nav), output_dir=None)


class BrowserRuntime:
    """One synchronous owner; worker messages serialize all engine effects."""
    def __init__(self):
        self.engine = None
        self.attempted = False
        self.failed = False
        self.callback = None
        self.pins = {}
        self.config_hash = None
        self.state = {'status': 'starting', 'phase': 'uninitialized', 'model_time_s': 0.}

    def _progress(self, row):
        self.state = {**self.state, **copy.deepcopy(row)}
        if self.callback is not None:
            self.callback(_json(row))

    def _capture(self):
        self.state = {**self.engine.snapshot(), 'status': 'ready',
            'integration_step_s': self.engine.dt,
            'execution_host': 'browser_wasm_worker' if sys.platform == 'emscripten' else 'cpython_adapter_test',
            'recording_fallback': False, 'adapter_config_sha256': self.config_hash,
            'source_files_sha256': copy.deepcopy(self.pins)}
        provenance = getattr(getattr(self.engine, 'nav', None), 'browser_metadata_provenance', None)
        if callable(provenance):
            self.state['browser_static_route_witnesses'] = provenance()
        return _json(self.state)

    def boot(self, config_json, progress_callback=None):
        if self.attempted:
            raise RuntimeError('A worker owns one fresh world; create a new worker to restart')
        self.attempted = True
        if progress_callback is not None and not callable(progress_callback):
            raise ValueError('Progress callback must be callable')
        self.callback = progress_callback
        try:
            config = _decode(config_json)
            self.config_hash = hashlib.sha256(_json(config).encode()).hexdigest()
            self._progress({'phase': 'verifying_browser_bundle'})
            paths, source, profile, self.pins = _configuration(config)
            self.engine = _make_engine(paths, source, profile, self._progress)
            return self._capture()
        except Exception as exc:
            self.failed = True
            self.state = {**self.state, 'status': 'error', 'error': str(exc),
                          'exception': type(exc).__name__}
            raise

    def _ready(self):
        if self.engine is None or self.failed:
            raise RuntimeError('Browser engine is not ready; inspect its error or start a fresh worker')

    def tick(self):
        self._ready()
        try:
            self.engine.step()
            return self._capture()
        except Exception as exc:
            self.failed = True
            self.state = {**self.state, 'status': 'error', 'error': str(exc),
                          'exception': type(exc).__name__}
            raise

    def command(self, command_json):
        self._ready()
        value = _decode(command_json)
        action = value.get('action')
        if action in ('pause', 'resume') and set(value) == {'action'}:
            self.engine.set_paused(action == 'pause')
        elif action == 'request_job' and set(value) == {'action', 'request_id', 'pickup', 'delivery'}:
            self.engine.request_job(value['pickup'], value['delivery'], value['request_id'])
        else:
            raise ValueError('Expected pause, resume or an identified pickup/delivery request')
        return self._capture()

    def snapshot(self):
        return _json(self.state)


_runtime = BrowserRuntime()


def boot(config_json, progress_callback=None):
    return _runtime.boot(config_json, progress_callback)


def tick():
    return _runtime.tick()


def command(command_json):
    return _runtime.command(command_json)


def snapshot():
    return _runtime.snapshot()
