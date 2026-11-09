"""Real loopback HTTP exercises the same read client used for an UltraC host."""
import copy
import hashlib
import http.client
import json
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from nanodrop_ultra_model import SOURCE, load_model, make_server
from nanodrop_ultra_network import HTTPResponseError, NanoDropUltraClient


@contextmanager
def running_model(**kwargs):
    server = make_server(port=0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
    thread.start()
    try:
        yield server, f'http://127.0.0.1:{server.server_port}/'
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def wire(server, method, path, token=None):
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
    try:
        headers = {} if token is None else {'Authorization': 'Bearer ' + token}
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


class NanoDropUltraModelTests(unittest.TestCase):
    def test_five_read_routes_keep_opaque_measurements_and_do_not_change_model(self):
        with running_model() as (server, url):
            before = copy.deepcopy(server.model)
            client = NanoDropUltraClient(url)
            self.assertTrue(client.system().data['Synthetic'])
            experiments = client.query_experiments().data
            identifier = experiments[0]['Id']
            self.assertEqual(client.experiment(identifier).data, experiments[0])
            detail = client.experiment_detail(identifier).data
            measurements = client.measurements(experiment_id=identifier).data
            self.assertEqual(detail['Measurements'], measurements)
            self.assertEqual(len(measurements), 2)
            self.assertEqual(measurements[0]['MeasurementBatch'], 9007199254740993)
            self.assertIsInstance(measurements[0]['DataJson'], str)
            self.assertTrue(json.loads(measurements[0]['DataJson'])['synthetic_only'])
            self.assertEqual(server.model, before)
            self.assertEqual(client.system().metadata['synthetic_model_sha256'],
                             hashlib.sha256(SOURCE.read_bytes()).hexdigest())

    def test_declared_synthetic_filter_pagination_and_time_choices(self):
        with running_model() as (_, url):
            client = NanoDropUltraClient(url)
            all_rows = client.query_experiments().data
            self.assertEqual(client.query_experiments(NameFilter='batch a', ApplicationFilter='DSdna').data,
                             all_rows[:1])
            self.assertEqual(client.query_experiments(PageNumber=1, PageSize=1).data, all_rows[1:])
            self.assertEqual(client.query_experiments(StartTime='2026-01-02T00:00:00Z').data, all_rows[1:])
            self.assertEqual(client.query_experiments(EndTimeStamp=1767355199999).data, all_rows[:1])
            self.assertEqual(len(client.measurements(start_page=1, page_count=1).data), 1)
            self.assertEqual(client.measurements(start_page=0, page_count=0).data, [])
            self.assertEqual(client.query_experiments(NameFilter='ä &/?#').data, [])

    def test_invalid_wire_queries_and_case_are_rejected(self):
        paths = ['/Experiment/Query?PageNumber=true', '/Experiment/Query?PageSize=0',
                 '/Experiment/Query?PageNumber=-1', '/Experiment/Query?pageNumber=0',
                 '/Experiment/Query?PageNumber=0&PageNumber=1',
                 '/Experiment/Query?StartTimeStamp=9223372036854775808',
                 '/Experiment/Query?StartTime=not-a-date', '/Measurement?experimentId=bad',
                 '/Measurement?StartPage=1', '/Measurement?startPage=2147483648',
                 '/Experiment/Id/not-a-uuid', '/System?unexpected=1']
        with running_model() as (server, _):
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(wire(server, 'GET', path)[0], 400)

    def test_missing_experiment_unsupported_reads_and_writes(self):
        with running_model() as (server, url):
            with self.assertRaises(HTTPResponseError) as caught:
                NanoDropUltraClient(url).experiment('99999999-9999-4999-8999-999999999999')
            self.assertEqual(caught.exception.response.status, 404)
            self.assertEqual(wire(server, 'GET', '/unknown')[0], 404)
            self.assertEqual(wire(server, 'GET', '/Measurement/FindPeak')[0], 501)
            for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
                status, headers, _ = wire(server, method, '/Measurement')
                self.assertEqual(status, 405)
                self.assertEqual(headers['Allow'], 'GET')

    def test_optional_bearer_authentication(self):
        secret = 'synthetic-test-key-only'
        with running_model(api_key=secret) as (server, url):
            for key in (None, 'wrong'):
                with self.subTest(key=key), self.assertRaises(HTTPResponseError) as caught:
                    NanoDropUltraClient(url, api_key=key).system()
                self.assertEqual(caught.exception.response.status, 401)
                self.assertNotIn(secret.encode(), caught.exception.response.raw)
            response = NanoDropUltraClient(url, api_key=secret).system()
            self.assertEqual(response.status, 200)
            self.assertTrue(response.metadata['synthetic_peer_detected'])
            self.assertNotIn(secret, json.dumps(response.metadata))
            self.assertEqual(wire(server, 'POST', '/Measurement')[0], 401)
            self.assertEqual(wire(server, 'POST', '/Measurement', token=secret)[0], 405)

    def test_model_bind_does_not_depend_on_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=AssertionError('No DNS for a bound model host')):
            with make_server(port=0) as server:
                self.assertGreater(server.server_port, 0)

    def test_pins_type_and_measurement_fields_are_checked(self):
        model = json.loads(SOURCE.read_bytes())
        mutations = [lambda value: value['protocol'].update(sha256='0' * 64),
                     lambda value: value.update(instrument_type='nanodrop_one_wifi'),
                     lambda value: value.update(synthetic=False),
                     lambda value: value['measurements'][0].update(IsDiscarded='false'),
                     lambda value: value['measurements'][0].update(MeasurementBatch=True),
                     lambda value: value['measurements'][0].update(ExtraUndocumented='bad'),
                     lambda value: value['synthetic_semantics'].update(timestamp_unit='unknown')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.json'
            for mutate in mutations:
                value = copy.deepcopy(model)
                mutate(value)
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                    load_model(path)

    def test_cli_archives_tcp_response_and_leaves_workflow_store_untouched(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        store = ROOT / 'exports/manual-workflows/nanodrop.sqlite3'
        before = store.read_bytes() if store.exists() else None
        with tempfile.TemporaryDirectory(dir=ROOT / 'exports', prefix='ultrac-network-test-') as directory:
            output = Path(directory) / 'capture'
            with running_model() as (_, url):
                command = [sys.executable, str(ROOT / 'scripts/run_nanodrop_ultra_network.py'),
                           'read', '--base-url', url, '--endpoint', 'measurements',
                           '--query', '{"startPage":0,"pageCount":1}', '--out', str(output)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                summary = json.loads(result.stdout)
                self.assertFalse(summary['workflow_imported'])
                self.assertFalse(summary['inventory_changed'])
                raw = (output / 'response.bin').read_bytes()
                metadata = json.loads((output / 'metadata.json').read_bytes())
                self.assertEqual(metadata['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(len(json.loads(raw)), 2)
                self.assertTrue(metadata['synthetic_peer_detected'])
                repeated = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual(repeated.returncode, 2)
                self.assertEqual((output / 'response.bin').read_bytes(), raw)
        self.assertEqual(store.read_bytes() if store.exists() else None, before)

    def test_cli_retains_http_error_without_exposing_remote_body_in_terminal(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'exports', prefix='ultrac-network-test-') as directory:
            output = Path(directory) / 'unauthorized'
            with running_model(api_key='synthetic-secret') as (_, url):
                result = subprocess.run([
                    sys.executable, str(ROOT / 'scripts/run_nanodrop_ultra_network.py'),
                    'read', '--base-url', url, '--endpoint', 'system', '--out', str(output)],
                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 401)
            self.assertNotIn('synthetic-secret', result.stdout + result.stderr)
            self.assertEqual(json.loads((output / 'metadata.json').read_bytes())['status'], 401)

    def test_cli_serves_the_model_on_an_ephemeral_loopback_port(self):
        process = subprocess.Popen([
            sys.executable, str(ROOT / 'scripts/run_nanodrop_ultra_network.py'),
            'serve', '--port', '0'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        try:
            line = ready.get(timeout=10)
            self.assertTrue(line, 'Server did not announce its endpoint')
            announcement = json.loads(line)
            self.assertTrue(announcement['synthetic'])
            self.assertFalse(announcement['hardware_verified'])
            response = NanoDropUltraClient(announcement['base_url']).system()
            self.assertEqual(response.data['SerialNumber'], 'SYN.ULTRAC.NET.001')
        finally:
            process.terminate()
            process.communicate(timeout=5)
