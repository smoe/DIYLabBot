"""Browser JSON adapter lifecycle; the physical engine is not duplicated here."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_browser_runtime as adapter


class FakeEngine:
    def __init__(self):
        self.now = 0.
        self.dt = .05
        self.paused = False
        self.calls = []
        self.fail = False

    def step(self):
        self.calls.append(('step',))
        if self.fail:
            raise RuntimeError('fixture own stopping proof rejected')
        if not self.paused:
            self.now = round(self.now+.05, 3)

    def snapshot(self):
        return {'format': 'solidcraftbot.building-fleet-live-snapshot/1',
                'session_id': 'fresh-fixture', 'model_time_s': self.now,
                'paused': self.paused, 'states': [], 'camera_frames': []}

    def set_paused(self, value):
        self.calls.append(('pause', value))
        self.paused = value

    def request_job(self, pickup, delivery, request_id):
        self.calls.append(('job', copy.deepcopy(pickup), copy.deepcopy(delivery), request_id))


class BrowserLifecycleTests(unittest.TestCase):
    def ready(self, callback=None):
        runtime = adapter.BrowserRuntime()
        engine = FakeEngine()
        paths, source, profile = {'map': 'immutable-path'}, {'fleet': 'source'}, {'patrol': 'policy'}
        def factory(actual_paths, actual_source, actual_profile, progress):
            self.assertEqual((actual_paths, actual_source, actual_profile), (paths, source, profile))
            progress({'phase': 'restored_exact_static_cache'})
            return engine
        with patch.object(adapter, '_configuration', return_value=(paths, source, profile, {'adapter': 'pin'})), \
                patch.object(adapter, '_make_engine', side_effect=factory) as make:
            value = json.loads(runtime.boot('{"root":"/fixture"}', callback))
        self.assertEqual(value['model_time_s'], 0.)
        self.assertEqual(value['integration_step_s'], engine.dt)
        self.assertFalse(value['recording_fallback'])
        self.assertEqual(value['source_files_sha256'], {'adapter': 'pin'})
        self.assertEqual(make.call_count, 1)
        return runtime, engine

    def test_boot_creates_one_fresh_world_and_serializes_progress(self):
        progress = []
        runtime, engine = self.ready(progress.append)
        self.assertEqual([json.loads(row)['phase'] for row in progress],
                         ['verifying_browser_bundle', 'restored_exact_static_cache'])
        with self.assertRaisesRegex(RuntimeError, 'one fresh world'):
            runtime.boot('{}')
        self.assertEqual(engine.calls, [])

    def test_tick_and_pause_delegate_once_without_wall_clock_catchup(self):
        runtime, engine = self.ready()
        self.assertEqual(json.loads(runtime.tick())['model_time_s'], .05)
        self.assertTrue(json.loads(runtime.command('{"action":"pause"}'))['paused'])
        self.assertEqual(json.loads(runtime.tick())['model_time_s'], .05)
        runtime.command('{"action":"resume"}')
        self.assertEqual(json.loads(runtime.tick())['model_time_s'], .1)
        self.assertEqual(engine.calls,
            [('step',), ('pause', True), ('step',), ('pause', False), ('step',)])

    def test_job_identity_and_only_declared_endpoints_cross_the_boundary(self):
        runtime, engine = self.ready()
        command = {'action': 'request_job', 'request_id': 'process-17',
                   'pickup': {'level': 'EG', 'area': 'R0_015'},
                   'delivery': {'level': 'OG3', 'area': 'R3_003'}}
        runtime.command(json.dumps(command))
        self.assertEqual(engine.calls, [('job', command['pickup'], command['delivery'], 'process-17')])
        for extra in ({'peer_positions': []}, {'pose_mm': [0, 0]}, {'vehicle_id': 'BF01'}):
            with self.assertRaises(ValueError):
                runtime.command(json.dumps({**command, **extra}))
        self.assertEqual(len(engine.calls), 1)

    def test_duplicate_json_fields_and_nonfinite_commands_fail_without_effect(self):
        runtime, engine = self.ready()
        for command in ('{"action":"pause","action":"resume"}',
                        '{"action":"pause","number":NaN}', '[]',
                        '{"action":"resume","positions":[]}'):
            with self.assertRaises(ValueError):
                runtime.command(command)
        self.assertEqual(engine.calls, [])
        self.assertEqual(json.loads(runtime.snapshot())['status'], 'ready')

    def test_runtime_error_freezes_last_accepted_state_and_cannot_repeat_effect(self):
        runtime, engine = self.ready()
        runtime.tick()
        engine.fail = True
        with self.assertRaisesRegex(RuntimeError, 'stopping proof'):
            runtime.tick()
        error = json.loads(runtime.snapshot())
        self.assertEqual(error['status'], 'error')
        self.assertEqual(error['model_time_s'], .05)
        with self.assertRaisesRegex(RuntimeError, 'not ready'):
            runtime.tick()
        self.assertEqual(engine.calls, [('step',), ('step',)])

    def test_failed_boot_has_no_recording_fallback(self):
        runtime = adapter.BrowserRuntime()
        with patch.object(adapter, '_configuration', side_effect=ValueError('altered native artifact')):
            with self.assertRaisesRegex(ValueError, 'altered native artifact'):
                runtime.boot('{}')
        self.assertEqual(json.loads(runtime.snapshot())['status'], 'error')
        self.assertIsNone(runtime.engine)

    def test_background_json_is_opaque_and_preserves_typed_signed_zero(self):
        runtime, engine = self.ready()
        request = {'kind': 'full_route', 'request_id': '1', 'vehicle_id': 'BF06',
                   'action': {'values': [0, 0.0, -0.0, 1.0]}}
        engine.drain_preparation_requests = lambda: [request]
        envelopes = json.loads(runtime.pending_jobs())
        # Only the envelope is decoded by JS; its nested JSON remains a string.
        wire = json.loads(json.dumps(envelopes))[0]
        self.assertIn('[0,0.0,-0.0,1.0]', wire['request_json'])
        self.assertEqual(wire['kind'], 'full_route')
        received = json.loads(wire['request_json'])
        self.assertIs(type(received['action']['values'][0]), int)
        self.assertIs(type(received['action']['values'][1]), float)
        self.assertEqual(adapter._json(received), adapter._json(request))

    def test_every_control_step_runs_without_rebuilding_a_presentation_snapshot(self):
        runtime, engine = self.ready()
        with patch.object(engine, 'snapshot', wraps=engine.snapshot) as snapshots:
            for _ in range(4):
                step = json.loads(runtime.tick(False))
                self.assertEqual(step['format'], 'solidcraftbot.building-fleet-live-step/1')
            self.assertEqual(engine.now, .2)
            self.assertEqual(engine.calls, [('step',)]*4)
            self.assertEqual(snapshots.call_count, 0)
            self.assertEqual(json.loads(runtime.snapshot())['model_time_s'], 0)
            self.assertEqual(json.loads(runtime.tick())['model_time_s'], .25)
            self.assertEqual(snapshots.call_count, 1)


class BrowserConfigurationTests(unittest.TestCase):
    def test_project_escape_and_unpinned_new_adapter_are_rejected(self):
        with self.assertRaises(ValueError):
            adapter._path('../outside')
        config = {name: 'exports/fake' for name in adapter.INPUTS}
        config.update(root=str(adapter.model.ROOT.resolve()), source_files_sha256={'old': 'hash'})
        with self.assertRaisesRegex(ValueError, 'adapters'):
            adapter._configuration(config)

    def fixture(self, root):
        def write(path, value):
            file = root/path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(value))
            return {'path': path, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
        source = write('model/building-fleet-demo.shared.json', {'fixture': True})
        profile = {'format': 'solidcraftbot.building-fleet-patrol/1',
            'sources': {'fleet': source},
            'patrol': {'termination': 'explicit_stop', 'startup': 'first_received_camera_frames',
                       'targets': '/missions/targets', 'selection': 'oldest_received_visit'},
            'recruitment': {'selection': 'lowest_feasible_route_eta',
                'diversion': 'observed_stationary_boundary', 'pickup_delivery': 'empty_inspection_visits',
                'acknowledgement': 'received_mission_and_completion'},
            'qualification': {'simulation_only': True, 'empty_vehicles': True,
                              'hardware_or_real_safety_qualified': False}}
        profile_pin = write('model/building-fleet-patrol.shared.json', profile)
        browser = {'format': 'solidcraftbot.building-fleet-browser/1',
            'sources': {'patrol': profile_pin},
            'session': {'scope': 'independent_live_session_per_page',
                        'start': 'new_patrol_world', 'recording_fallback': False},
            'runtime': {'engine': 'pyodide', 'execution': 'module_web_worker',
                        'static_route_witnesses': 'original_pinned_metadata_for_bit_identical_geometry',
                        'pacing': 'source_step_without_wall_clock_catchup'},
            'qualification': profile['qualification']}
        write('model/building-fleet-browser.shared.json', browser)
        for name in ('building_fleet_browser_runtime.py', 'building_fleet_patrol.py',
                     'building_fleet_browser_navigation.py',
                     'building_fleet_browser_worker.mjs', 'building_fleet_browser_transport.js'):
            write('scripts/'+name, {'fixture_source': name})
        pins = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}
        config = {name: 'exports/fake' for name in adapter.INPUTS}
        config.update(profile=profile_pin['path'], root=str(root), source_files_sha256=pins)
        return config, browser

    def test_complete_source_closure_is_verified_before_loading_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config, browser = self.fixture(root)
            with patch.object(adapter.model, 'ROOT', root), \
                    patch.object(adapter.model, 'load', return_value={'fixture': True}) as load:
                paths, source, profile, pins = adapter._configuration(config)
                self.assertEqual(paths['profile'], root/config['profile'])
                self.assertEqual(source, {'fixture': True})
                self.assertEqual(pins, config['source_files_sha256'])
                load.assert_called_once()
                (root/'scripts/building_fleet_patrol.py').write_text('changed')
                with self.assertRaisesRegex(ValueError, 'Changed'):
                    adapter._configuration(config)

    def test_recording_fallback_is_rejected_even_when_its_bytes_are_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config, browser = self.fixture(root)
            browser['session']['recording_fallback'] = True
            path = root/'model/building-fleet-browser.shared.json'
            path.write_text(json.dumps(browser))
            config['source_files_sha256'][path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(adapter.model, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'without recording'):
                    adapter._configuration(config)

    def test_compact_contract_pins_cache_and_requires_background_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            old, browser = self.fixture(root)
            browser['format'] = 'solidcraftbot.building-fleet-browser/2'
            browser['runtime'].update(static_geometry='source_bound_lossless_runtime_cache',
                route_preparation='background_worker_with_checked_rolling_prefix')
            path = root/'model/building-fleet-browser.shared.json'
            path.write_text(json.dumps(browser))
            cache = root/'exports/cache-report.json'
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text('{"fixture":"static geometry only"}')
            pins = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in root.rglob('*') if p.is_file()}
            config = {name: old[name] for name in ('root', 'profile')}
            config.update(static_runtime_cache='exports/cache-report.json', source_files_sha256=pins)
            with patch.object(adapter.model, 'ROOT', root), patch.object(adapter.model, 'load', return_value={}):
                paths, _, _, _ = adapter._configuration(config)
                self.assertEqual(paths['static_runtime_cache'], cache)
                cache.write_text('{"fixture":"changed"}')
                with self.assertRaisesRegex(ValueError, 'Changed'):
                    adapter._configuration(config)


if __name__ == '__main__':
    unittest.main()
