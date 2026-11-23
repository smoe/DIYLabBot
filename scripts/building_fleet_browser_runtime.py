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
COMPACT_INPUTS = frozenset({'profile', 'static_runtime_cache'})
OPTIONAL = frozenset({'browser_source', 'browser_config_sha256'})
_VERIFIED_EXTRACTION = None


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
    compact = 'static_runtime_cache' in config
    inputs = COMPACT_INPUTS if compact else INPUTS
    required = inputs | {'root', 'source_files_sha256'}
    if not required <= set(config) or set(config)-required-OPTIONAL:
        raise ValueError('Closed browser engine configuration required')
    if config['root'] != str(model.ROOT.resolve()):
        raise ValueError('Browser project root differs from the imported engine')
    paths = {name: _path(config[name]) for name in inputs}
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
    # Static artifact bytes have their own exact report verifier in restore().
    # Delegate those large inputs to it, rather than hashing the same full
    # cache again here before its mandatory verification and first access.
    delegated = {}
    if compact:
        report_name = paths['static_runtime_cache'].relative_to(model.ROOT).as_posix()
        if report_name not in pins:
            raise ValueError('The static derivation report must be in the source closure')
        cache_report = model.read_json(model.resolve_pin({'path': report_name, 'sha256': pins[report_name]}))
        for ref in cache_report.get('files', {}).values():
            if type(ref) is not dict or pins.get(ref.get('path')) != ref.get('sha256'):
                raise ValueError('Static cache artifacts differ from the verified bundle closure')
            delegated[ref['path']] = ref['sha256']
    # Ordinary source inputs retain their existing source-pin check. A compact
    # engine cannot run before restore has verified every delegated artifact.
    extracted = (_VERIFIED_EXTRACTION is not None and
        pins == {name: ref['sha256'] for name, ref in _VERIFIED_EXTRACTION['files'].items()})
    if not extracted:
        for path, digest in pins.items():
            _path(path)
            if delegated.get(path) != digest:
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
    expected_format = 'solidcraftbot.building-fleet-browser/2' if compact else 'solidcraftbot.building-fleet-browser/1'
    if (browser.get('format') != expected_format or
            browser.get('session') != {'scope': 'independent_live_session_per_page',
                'start': 'new_patrol_world', 'recording_fallback': False} or
            browser.get('runtime', {}).get('engine') != 'pyodide' or
            browser.get('runtime', {}).get('execution') != 'module_web_worker' or
            browser.get('runtime', {}).get('static_route_witnesses') !=
                'original_pinned_metadata_for_bit_identical_geometry' or
            browser.get('runtime', {}).get('pacing') != 'source_step_without_wall_clock_catchup'):
        raise ValueError('A fresh independent browser-worker world without recording fallback is required')
    if compact and (browser['runtime'].get('static_geometry') != 'source_bound_lossless_runtime_cache' or
            browser['runtime'].get('route_preparation') != 'background_worker_with_checked_rolling_prefix'):
        raise ValueError('The compact runtime requires checked geometry and background preparation')
    if model.resolve_pin(browser['sources']['patrol']) != paths['profile']:
        raise ValueError('Browser profile differs from its leading pinned source')
    profile = model.read_json(paths['profile'])
    source = model.load(model.resolve_pin(profile['sources']['fleet']))
    patrol_policy = profile.get('patrol', {})
    if (profile.get('format') != 'solidcraftbot.building-fleet-patrol/1' or
            patrol_policy.get('startup') not in ('first_received_camera_frames', 'own_received_camera_frame') or
            patrol_policy != {'termination': 'explicit_stop',
                'startup': patrol_policy.get('startup'), 'targets': '/missions/targets',
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
    from building_fleet_patrol import PatrolWorldRunner

    if 'static_runtime_cache' in paths:
        from building_fleet_runtime_cache import restore
        progress({'phase': 'restoring_checked_static_geometry'})
        witness = _static_verification()
        prepared = restore(paths['static_runtime_cache'], source, progress=progress, initial_level='EG', **witness)
        engine = PatrolWorldRunner(source, prepared['nav'], prepared['graph'],
            prepared['catalog'], prepared['planner'], profile, progress=progress,
            geometry_checker=prepared['geometry_checks'], output_dir=None,
            scan_geometry=prepared['scan_geometry'], zone_regions=prepared['zone_regions'],
            scan_indices=prepared.get('scan_indices'))
        if prepared.get('static_ray_cache') is not None:
            from building_fleet_runtime_cache import seed_static_rays
            engine.static_ray_cache = seed_static_rays(engine.world, prepared['static_ray_cache'])
        return engine

    from building_fleet_browser_navigation import BrowserNavigation
    from building_fleet_patrol_cache import prepare_cached
    from building_fleet_geometry_checks import GeometryChecks
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
        # Progress cannot move the cached executed clock/poses between actual
        # presentation snapshots. Its own observation time stays in the event.
        if 'phase' in row:
            self.state = {**self.state, 'phase': copy.deepcopy(row['phase'])}
        if self.callback is not None:
            self.callback(_json(row))

    def _capture(self):
        self.state = {**self.engine.snapshot(), 'status': 'ready',
            'integration_step_s': self.engine.dt,
            'execution_host': 'browser_wasm_worker' if sys.platform == 'emscripten' else 'cpython_adapter_test',
            'recording_fallback': False, 'adapter_config_sha256': self.config_hash,
            'source_files_sha256': copy.deepcopy(self.pins)}
        rate = getattr(self.engine, 'source', {}).get('camera_presentation', {}).get('selected_rate_hz', 1/self.engine.dt)
        self.state['snapshot_interval_steps'] = max(1, round(1/(rate*self.engine.dt)))
        self.state['has_motion'] = self._has_motion()
        provenance = getattr(getattr(self.engine, 'nav', None), 'browser_metadata_provenance', None)
        if callable(provenance):
            self.state['browser_static_route_witnesses'] = provenance()
        if hasattr(self.engine, 'static_ray_cache'):
            self.state['static_ray_cache'] = copy.deepcopy(self.engine.static_ray_cache)
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
            if 'static_runtime_cache' in paths:
                self.engine.configure_background_preparation(self.config_hash)
            return self._capture()
        except Exception as exc:
            self.failed = True
            self.state = {**self.state, 'status': 'error', 'error': str(exc),
                          'exception': type(exc).__name__}
            raise

    def _ready(self):
        if self.engine is None or self.failed:
            raise RuntimeError('Browser engine is not ready; inspect its error or start a fresh worker')

    def _has_motion(self):
        return any(row.get('driver') is not None and abs(row['driver'].v) > 1e-8
                   for row in getattr(self.engine, 'vehicles', {}).values())

    def tick(self, capture=True):
        self._ready()
        if type(capture) is not bool:
            raise ValueError('Explicit presentation snapshot choice required')
        try:
            self.engine.step()
            if capture:
                return self._capture()
            return _json({'format': 'solidcraftbot.building-fleet-live-step/1',
                'model_time_s': self.engine.now, 'paused': self.engine.paused,
                'integration_step_s': self.engine.dt, 'has_motion': self._has_motion()})
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

    def pending_jobs(self):
        self._ready()
        # Keep the inner JSON opaque in JavaScript: JSON.parse/stringify would
        # turn 0.0/-0.0 into integer 0 and invalidate exact typed PVA fences.
        return _json([{'kind': row['kind'], 'request_json': _json(row),
                       'starter_installed': getattr(self.engine, 'vehicles', {}).get(row.get('vehicle_id'), {}).get('driver') is not None}
                      for row in self.engine.drain_preparation_requests()])

    def complete_job(self, result_json):
        self._ready()
        return _json(self.engine.accept_prepared_route(_decode(result_json)))


_runtime = BrowserRuntime()


def boot(config_json, progress_callback=None):
    return _runtime.boot(config_json, progress_callback)


def tick(capture=True):
    return _runtime.tick(capture)


def command(command_json):
    return _runtime.command(command_json)


def snapshot():
    return _runtime.snapshot()


def pending_jobs():
    return _runtime.pending_jobs()


def complete_job(result_json):
    return _runtime.complete_job(result_json)


_planner_context = None


def bind_verified_extraction(manifest_json):
    """Record the loader's completed SHA/size check inside its private worker.

    The module loader calls this only after verifying every original member
    before writing/importing it. These source/data files remain immutable in
    the worker; no simulation command exposes filesystem writes. Direct
    adapter calls without this receipt retain ordinary file verification.
    """
    global _VERIFIED_EXTRACTION
    if sys.platform != 'emscripten' or _VERIFIED_EXTRACTION is not None or _runtime.attempted or _planner_context is not None:
        raise RuntimeError('A private browser loader may bind its verified extraction only once before boot')
    manifest = _decode(manifest_json)
    if (manifest.get('root_dir') != '/project' or
            manifest.get('format') != 'solidcraftbot.building-fleet-browser-bundle/2' or
            type(manifest.get('files')) is not dict or not manifest['files']):
        raise ValueError('The loader needs its complete verified compact manifest')
    for name, ref in manifest['files'].items():
        _path(name)
        if type(ref) is not dict or set(ref) != {'sha256','bytes'} or type(ref['bytes']) is not int or ref['bytes'] < 0:
            raise ValueError('Exact original file sizes and hashes required')
    _VERIFIED_EXTRACTION = copy.deepcopy(manifest)


def _static_verification():
    if _VERIFIED_EXTRACTION is None:
        return {}
    return {'verified_files': copy.deepcopy(_VERIFIED_EXTRACTION['files']),
            'verification_receipt': copy.deepcopy(_VERIFIED_EXTRACTION['static_cache_verification'])}


def boot_planner(config_json, progress_callback=None):
    """Restore immutable planning geometry; never create a second physical world."""
    global _planner_context
    if _planner_context is not None:
        raise RuntimeError('A preparation worker may initialize only once')
    config = _decode(config_json)
    paths, source, _profile, _pins = _configuration(config)
    if 'static_runtime_cache' not in paths:
        raise ValueError('A background planner requires the checked compact runtime')
    from building_fleet_runtime_cache import restore
    def progress(row):
        if progress_callback is not None:
            progress_callback(_json(row))
    prepared = restore(paths['static_runtime_cache'], source, progress=progress, initial_level=None,
                       **_static_verification())
    _planner_context = {**prepared, 'source': source,
        'source_binding': hashlib.sha256(_json(config).encode()).hexdigest()}
    return _json({'status': 'ready'})


def prepare_job(request_json):
    if _planner_context is None:
        raise RuntimeError('Background geometry is not initialized')
    request = _decode(request_json)
    if request.get('source_binding') != _planner_context['source_binding']:
        raise ValueError('Preparation request belongs to different runtime sources')
    from building_fleet_background import prepare_route
    return _json(prepare_route(request, _planner_context))
