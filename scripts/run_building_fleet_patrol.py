#!/usr/bin/env python3
"""Serve an opt-in active, empty-vehicle BF01 experiment on loopback only.

The existing motion, scan, braking, resource and geometry checks remain in
the Python engine. The browser only displays already executed states.
"""
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import re
import threading
import time
from urllib.parse import urlsplit

import building_fleet_model as model
import build_building_fleet_demo as browser
import export_building_walkthrough_freecad as native
from run_building_fleet import artifact, project_path

PROFILE = model.ROOT / 'model/building-fleet-patrol.shared.json'
LIVE_VIEW = model.ROOT / 'scripts/building_fleet_live_view.js'


def load_profile(path=PROFILE):
    """Reject unsupported policies instead of silently using a different one."""
    value = model.read_json(project_path(path))
    startup=value.get('patrol',{}).get('startup')
    if startup not in ('first_received_camera_frames','own_received_camera_frame'):
        raise ValueError('Explicit supported received-camera startup policy required')
    expected = {
        'format': 'solidcraftbot.building-fleet-patrol/1', 'id': 'BF01-Patrol',
        'sources': {'fleet': artifact(model.ROOT / 'model/building-fleet-demo.shared.json')},
        'patrol': {'termination': 'explicit_stop', 'startup': startup,
                   'targets': '/missions/targets',
                   'selection': 'oldest_received_visit'},
        'recruitment': {'selection': 'lowest_feasible_route_eta',
            'diversion': 'observed_stationary_boundary',
            'pickup_delivery': 'empty_inspection_visits',
            'acknowledgement': 'received_mission_and_completion'},
        'qualification': {'simulation_only': True, 'empty_vehicles': True,
            'loads_implemented': False, 'workflow_binding_implemented': False,
            'network_video_implemented': False, 'full_mission_coverage_verified': False,
            'native_full_program_verified': False, 'independent_export_verified': False,
            'hardware_or_real_safety_qualified': False}}
    if value != expected:
        raise ValueError('Unsupported or stale patrol source; review its explicit policy and fleet pin')
    model.resolve_pin(value['sources']['fleet'])
    return value


def build_page(source, profile, args, output, *, progressive_output=None):
    """Reuse the checked native world and the existing physical monitor wall."""
    from export_building_fleet_vehicle_freecad import checked_camera_report
    camera = project_path(args.camera_report)
    checked_camera_report(camera)
    mesh_path = project_path(args.vehicle_mesh)
    vehicle = model.read_json(mesh_path)
    native.verify_pins(vehicle['source_files_sha256'])
    if (vehicle.get('format') != 'solidcraftbot.building-fleet-vehicle-mesh/1'
            or vehicle['camera_report'] != artifact(camera)):
        raise ValueError('Source-matched native vehicle mesh required')
    import tr01_camera_model as kit
    expected = {b['id'] for b in kit.expanded(kit.load())['bodies'] if b['role'] != 'viewing_cone'}
    if {g['id'] for g in vehicle['scene']['groups']} != expected:
        raise ValueError('Complete physical vehicle mesh required')
    world = project_path(args.walkthrough_export) / 'world-build-report.json'
    normal, pins = browser.world_presentation(world, include_monitor_overlay=True,
                                               progressive_output=progressive_output)
    payload = {'vehicle_mesh': vehicle, 'camera_presentation': source['camera_presentation'],
        'live': {'state_url': '/api/state', 'jobs_url': '/api/jobs',
            'control_url': '/api/control', 'poll_interval_ms':
                round(1000 / source['camera_presentation']['selected_rate_hz']),
            'targets': source['missions']['targets']},
        'presentation': {'atrium_monitors': True, 'start_stop': 'camera-wall',
                         'autoplay': True, 'follow': False},
        'qualification': profile['qualification']}
    text = browser.opt_in_html(normal, payload)
    before = 'BuildingFleetView.mount(fleetBridge,fleetPayload)'
    if text.count(before) != 1:
        raise ValueError('Existing fleet bootstrap changed')
    text = text.replace(before, 'BuildingFleetLiveView.mount(fleetBridge,fleetPayload)')
    script = LIVE_VIEW.read_text().replace('</script', '<\\/script')
    text = text.replace('</head>', '<script>' + script + '</script></head>')
    (output / 'index.html').write_text(text)
    pins.update({str(p.relative_to(model.ROOT)): model.digest(p)
                 for p in (PROFILE, LIVE_VIEW, browser.VIEW, Path(__file__))})
    pins.update({mesh_path.relative_to(model.ROOT).as_posix(): model.digest(mesh_path)})
    native.verify_pins(pins)
    result = {'format': 'solidcraftbot.building-fleet-patrol-build/1',
        'passed': True, 'source_files_sha256': pins,
        'html_sha256': model.digest(output / 'index.html'),
        'qualification': profile['qualification'],
        'scope': 'Active local empty-vehicle experiment; no completed fleet or load qualification'}
    (output / 'build-report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def prepare_engine(source, profile, args, output, progress):
    from building_fleet_routes import Navigation
    from building_fleet_runner import prepare_program
    from building_fleet_geometry_checks import GeometryChecks
    from building_fleet_patrol import PatrolWorldRunner
    progress({'phase': 'checking_navigation'})
    if args.navigation_cache:
        nav = Navigation.from_cache(source, project_path(args.walkthrough_export),
                                    project_path(args.navigation_cache))
    else:
        nav = Navigation(source, project_path(args.walkthrough_export))
    if args.graph_cache_report:
        if not args.resource_cache:
            raise ValueError('A graph cache also needs its matching resource cache')
        from building_fleet_patrol_cache import prepare_cached
        prepared = prepare_cached(source, nav, project_path(args.graph_cache_report),
                                  project_path(args.resource_cache), progress=progress)
    else:
        prepared = prepare_program(source, nav, progress=progress,
            resource_cache=project_path(args.resource_cache) if args.resource_cache else None)
    return PatrolWorldRunner(source, nav, *prepared, profile,
        progress=progress, geometry_checker=GeometryChecks(source, nav),
        output_dir=output / 'engine-evidence')


class Application:
    """Serialize effects in one worker; HTTP reads never wait for a geometry step."""
    def __init__(self, source, profile, output, factory):
        self.source, self.profile, self.output, self.factory = source, profile, output, factory
        self.lock = threading.Lock()
        self.commands = queue.Queue(maxsize=100)
        self.stop = threading.Event()
        self.paused = False
        self.requests = {}
        self.command_errors = []
        self.state = {'format': 'solidcraftbot.building-fleet-live-state/1',
                      'status': 'starting', 'phase': 'preparing', 'time_s': 0}
        self.journal = (output / 'commands.jsonl').open('x', encoding='utf-8')
        self.thread = threading.Thread(target=self.run, name='BF01-patrol', daemon=True)

    def record(self, event, **fields):
        with self.lock:
            self.journal.write(json.dumps({'event': event, **fields}, allow_nan=False) + '\n')
            self.journal.flush()

    def progress(self, row):
        with self.lock:
            ready = self.state.get('format') == 'solidcraftbot.building-fleet-live-snapshot/1'
            self.state = {**self.state, **row, 'status': 'ready' if ready else 'starting'}
        print(json.dumps(row), flush=True)

    def snapshot(self):
        with self.lock:
            return {**copy.deepcopy(self.state), 'paused': self.paused,
                    'command_errors': copy.deepcopy(self.command_errors)}

    def control(self, action):
        if action not in ('pause', 'resume'):
            raise ValueError('Expected pause or resume')
        with self.lock:
            self.paused = action == 'pause'
        self.record('control', action=action)
        return {'status': 'accepted', 'paused': self.paused}

    def request(self, value):
        if type(value) is not dict or set(value) != {'request_id', 'pickup', 'delivery'}:
            raise ValueError('Expected request_id, pickup and delivery')
        key = value['request_id']
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', key):
            raise ValueError('A bounded nonempty request identity is required')
        targets = {(r['level'], r['area']) for r in self.source['missions']['targets']}
        for name in ('pickup', 'delivery'):
            target = value[name]
            if (type(target) is not dict or set(target) != {'level', 'area'}
                    or (target['level'], target['area']) not in targets):
                raise ValueError('Only existing permitted source targets may be requested')
        if value['pickup'] == value['delivery']:
            raise ValueError('The empty recruitment exercise needs different targets')
        with self.lock:
            if self.state['status'] == 'error':
                raise ValueError('The engine stopped; inspect its reported error')
            previous = self.requests.get(key)
            if previous is not None:
                if previous != value:
                    raise ValueError('Request identity already belongs to different endpoints')
                return {'status': 'queued_for_engine', 'request_id': key}
            if len(self.requests) >= 100:
                raise ValueError('This bounded test session already holds 100 requests')
            try:
                self.commands.put_nowait(copy.deepcopy(value))
            except queue.Full as exc:
                raise ValueError('Request queue is full') from exc
            self.requests[key] = copy.deepcopy(value)
        self.record('request_queued', request=value)
        return {'status': 'queued_for_engine', 'request_id': key}

    def run(self):
        engine = None
        try:
            engine = self.factory(self.progress)
            with self.lock:
                self.state = {**engine.snapshot(), 'status': 'ready', 'paused': self.paused}
            started = time.monotonic()
            while not self.stop.is_set():
                began = time.monotonic()
                while True:
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        result = engine.request_job(command['pickup'], command['delivery'], command['request_id'])
                        self.record('request_received', request_id=command['request_id'], result=result)
                    except ValueError as exc:
                        self.record('request_rejected', request_id=command['request_id'], error=str(exc))
                        with self.lock:
                            self.command_errors.append({'request_id': command['request_id'],
                                                        'error': str(exc)})
                            self.command_errors = self.command_errors[-100:]
                if not self.paused:
                    engine.step()
                value = engine.snapshot()
                value.update(status='ready', wall_elapsed_s=time.monotonic() - started,
                             paused=self.paused)
                with self.lock:
                    self.state = value
                # Never accelerate model time to catch up after an expensive check.
                self.stop.wait(max(0, engine.dt - (time.monotonic() - began)))
        except Exception as exc:
            self.record('engine_error', error=str(exc), exception=type(exc).__name__)
            with self.lock:
                self.state = {**self.state, 'status': 'error', 'error': str(exc)}
            print(json.dumps({'phase': 'error', 'error': str(exc)}), flush=True)
        finally:
            if engine is not None and engine.evidence is not None:
                receipt = engine.evidence.close()
                (self.output / 'engine-evidence-receipt.json').write_text(
                    json.dumps(receipt, indent=2) + '\n')

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
        if not self.thread.is_alive():
            self.journal.close()


def handler(application, html):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_json(self, status, value):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/state':
                self.send_json(200, application.snapshot())
            elif path in ('/', '/index.html'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            else:
                self.send_json(404, {'error': 'Not found'})

        def do_POST(self):
            # A third-party page may not recruit vehicles through the local demo.
            origin = self.headers.get('Origin')
            allowed = {'http://127.0.0.1:' + str(self.server.server_port),
                       'http://localhost:' + str(self.server.server_port)}
            if origin is not None and origin not in allowed:
                self.send_json(403, {'error': 'Same-origin requests only'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Bounded JSON request body required')
                value = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == '/api/jobs':
                    result = application.request(value)
                elif path == '/api/control' and type(value) is dict and set(value) == {'action'}:
                    result = application.control(value['action'])
                else:
                    raise ValueError('Unknown request')
                self.send_json(202, result)
            except (ValueError, TypeError, KeyError) as exc:
                self.send_json(400, {'error': str(exc)})
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('walkthrough-export', 'camera-report', 'vehicle-mesh', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--navigation-cache')
    parser.add_argument('--resource-cache')
    parser.add_argument('--graph-cache-report', help='Optional current source-pinned static preparation report')
    parser.add_argument('--initial-request', help='Optional explicit empty test-request JSON, queued before patrol starts')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    source, profile = model.load(), load_profile()
    output = project_path(args.output_dir, output=True)
    output.mkdir(parents=True, exist_ok=False)
    build_page(source, profile, args, output)
    runtime_modules = ('building_fleet_patrol.py', 'run_building_fleet_patrol.py',
        'building_fleet_runner.py', 'building_fleet_missions.py',
        'building_fleet_resources.py', 'building_fleet_geometry_checks.py',
        'building_fleet_control.py', 'building_fleet_motion.py',
        'building_fleet_comm.py', 'building_fleet_sim.py', 'building_fleet_services.py')
    pins = {**model.source_pins(source), **model.protected_pins(),
        str(PROFILE.relative_to(model.ROOT)): model.digest(PROFILE),
        **{'scripts/' + name: model.digest(model.ROOT / 'scripts' / name)
           for name in runtime_modules}}
    initial_request = None
    if args.initial_request:
        initial = artifact(args.initial_request)
        initial_request = model.read_json(model.resolve_pin(initial))
        pins[initial['path']] = initial['sha256']
    (output / 'runtime-source-start.json').write_text(json.dumps(pins, indent=2) + '\n')
    application = Application(source, profile, output,
        lambda progress: prepare_engine(source, profile, args, output, progress))
    if initial_request is not None:
        application.request(initial_request)
    server = ThreadingHTTPServer(('127.0.0.1', args.port),
                                 handler(application, (output / 'index.html').read_bytes()))
    application.thread.start()
    print(json.dumps({'url': 'http://127.0.0.1:' + str(server.server_port) + '/',
                      'scope': 'active local empty-vehicle experiment'}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.close()


if __name__ == '__main__':
    main()
