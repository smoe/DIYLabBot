"""Real loopback reads for the bounded Ultra client, without a device or workflow."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import ssl
import socket
from socketserver import TCPServer
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from nanodrop_ultra_network import (NanoDropUltraClient, NanoDropNetworkError,
    HTTPResponseError, ResponseFormatError, ResponseTooLargeError,
    load_protocol, endpoint_path, validate_query)

IDENTIFIER = '11111111-2222-4333-8444-555555555555'
KEY = 'SYN.only-for-loopback-tests.token'


@contextmanager
def peer(body=b'{}', status=200, headers=None, required_key=None, delay=0, send_length=True):
    """A deliberately small raw HTTP peer, independent of the model server."""
    state = SimpleNamespace(requests=[])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            state.requests.append({'method': self.command, 'path': self.path,
                                   'authorization': self.headers.get('Authorization')})
            if delay:
                time.sleep(delay)
            unauthorized = required_key is not None and self.headers.get('Authorization') != 'Bearer ' + required_key
            self.send_response(401 if unauthorized else status)
            content = b'{"error":"authentication required"}' if unauthorized else body
            if send_length:
                self.send_header('Content-Length', str(len(content)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            state.requests.append({'method': self.command, 'path': self.path})
            self.send_error(405)
    class PeerServer(ThreadingHTTPServer):
        def server_bind(self):
            TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address[:2]
    server = PeerServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    state.base_url = 'http://127.0.0.1:' + str(server.server_port) + '/'
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ContractTests(unittest.TestCase):
    def test_paths_and_query_types_come_from_the_documented_source(self):
        protocol = load_protocol()
        self.assertEqual(protocol['default_port'], 54011)
        self.assertEqual(endpoint_path('system'), '/System')
        self.assertEqual(endpoint_path('query_experiments'), '/Experiment/Query')
        self.assertEqual(endpoint_path('experiment', IDENTIFIER.upper()), '/Experiment/Id/' + IDENTIFIER)
        self.assertEqual(endpoint_path('experiment_detail', UUID(IDENTIFIER)), '/Experiment/Detail/Id/' + IDENTIFIER)
        self.assertEqual(endpoint_path('measurements'), '/Measurement')
        self.assertEqual(protocol['endpoints']['measurements']['query']['experimentId'], 'uuid')

    def test_integer_ranges_are_checked_without_inventing_page_origins(self):
        accepted = {'PageNumber': -(2 ** 31), 'PageSize': 2 ** 31 - 1,
                    'StartTimeStamp': -(2 ** 63), 'EndTimeStamp': 2 ** 63 - 1}
        self.assertEqual(validate_query('query_experiments', accepted), accepted)
        for name, value in [('PageNumber', 2 ** 31), ('PageNumber', -(2 ** 31) - 1),
                            ('PageSize', True), ('PageSize', '1'), ('StartTimeStamp', 2 ** 63),
                            ('EndTimeStamp', float('nan'))]:
            with self.subTest(name=name, value=value), self.assertRaises(NanoDropNetworkError):
                validate_query('query_experiments', {name: value})
        self.assertEqual(validate_query('measurements', {'startPage': -1, 'pageCount': 0}),
                         {'startPage': -1, 'pageCount': 0})

    def test_exact_query_case_and_types_are_required(self):
        for endpoint, params in [('query_experiments', {'nameFilter': 'SYN'}),
                                 ('query_experiments', {'NameFilter': 3}),
                                 ('measurements', {'ExperimentId': IDENTIFIER}),
                                 ('system', {'PageNumber': 0})]:
            with self.subTest(endpoint=endpoint, params=params), self.assertRaises(NanoDropNetworkError):
                validate_query(endpoint, params)

    def test_optional_none_is_omitted_without_dropping_integer_zero(self):
        self.assertEqual(validate_query('query_experiments', {'NameFilter': None, 'PageNumber': 0}),
                         {'PageNumber': 0})
        with self.assertRaises(NanoDropNetworkError):
            validate_query('query_experiments', {'nameFilter': None})

    def test_datetime_requires_an_explicit_rfc3339_timezone_without_epoch_conversion(self):
        for value in ['2026-11-09T12:34:56Z', '2026-11-09T13:34:56.123+01:00']:
            self.assertEqual(validate_query('query_experiments', {'StartTime': value})['StartTime'], value)
        for value in ['2026-11-09', '2026-11-09T12:34:56', '2026-02-30T00:00:00Z', 1234]:
            with self.subTest(value=value), self.assertRaises(NanoDropNetworkError):
                validate_query('query_experiments', {'StartTime': value})

    def test_uuid_validation_prevents_path_or_query_injection(self):
        for value in ['../System', IDENTIFIER + '?x=y', 'not-a-uuid', 123, None]:
            with self.subTest(value=value), self.assertRaises(NanoDropNetworkError):
                endpoint_path('experiment', value)
        self.assertEqual(validate_query('measurements', {'experimentId': UUID(IDENTIFIER)})['experimentId'], IDENTIFIER)
        with self.assertRaises(NanoDropNetworkError):
            endpoint_path('system', IDENTIFIER)


class ClientTests(unittest.TestCase):
    def test_five_get_methods_preserve_paths_casing_and_values(self):
        with peer(b'[{"opaque":true}]') as server:
            client = NanoDropUltraClient(server.base_url)
            self.assertEqual(client.system().data, [{'opaque': True}])
            filters = {'NameFilter': 'SYN name / \u00e4', 'ApplicationFilter': 'dsDNA',
                       'PageNumber': -1, 'PageSize': 0, 'StartTimeStamp': 123456789012345,
                       'EndTimeStamp': 123456789012346, 'StartTime': '2026-11-09T00:00:00Z',
                       'EndTime': '2026-11-10T00:00:00+01:00'}
            result = client.query_experiments(**filters)
            self.assertEqual(parse_qs(urlsplit(result.request_path).query), {k: [str(v)] for k, v in filters.items()})
            client.experiment(IDENTIFIER)
            client.experiment_detail(IDENTIFIER)
            result = client.measurements(IDENTIFIER, -1, 0)
            self.assertEqual(parse_qs(urlsplit(result.request_path).query),
                             {'experimentId': [IDENTIFIER], 'startPage': ['-1'], 'pageCount': ['0']})
            self.assertEqual([urlsplit(r['path']).path for r in server.requests],
                             ['/System', '/Experiment/Query', '/Experiment/Id/' + IDENTIFIER,
                              '/Experiment/Detail/Id/' + IDENTIFIER, '/Measurement'])
            self.assertTrue(all(r['method'] == 'GET' and r['authorization'] is None for r in server.requests))

    def test_no_automatic_pagination_or_embedded_json_interpretation(self):
        value = {'Items': [{'DataJson': '{"value": 12}', 'IsDiscarded': True}], 'Next': '/Measurement?startPage=1'}
        with peer(json.dumps(value).encode()) as server:
            response = NanoDropUltraClient(server.base_url).measurements()
            self.assertEqual(response.data, value)
            self.assertIsInstance(response.data['Items'][0]['DataJson'], str)
            self.assertEqual(len(server.requests), 1)
            self.assertFalse(response.metadata['workflow_imported'])

    def test_optional_bearer_key_and_unauthorized_response(self):
        with peer(required_key=KEY) as server:
            with self.assertRaises(HTTPResponseError) as error:
                NanoDropUltraClient(server.base_url).system()
            self.assertEqual(error.exception.response.status, 401)
            self.assertEqual(error.exception.response.data, {'error': 'authentication required'})
            response = NanoDropUltraClient(server.base_url, api_key=KEY).system()
            self.assertEqual(server.requests[-1]['authorization'], 'Bearer ' + KEY)
            self.assertNotIn(KEY, json.dumps(response.metadata))
            self.assertNotIn('Authorization', json.dumps(response.metadata))

    def test_redirects_are_not_followed_even_with_a_bearer_key(self):
        with peer() as target:
            for status in [301, 302, 303, 307, 308]:
                with self.subTest(status=status), peer(b'{}', status, {'Location': target.base_url + 'System'}) as source:
                    with self.assertRaises(HTTPResponseError) as error:
                        NanoDropUltraClient(source.base_url, api_key=KEY).system()
                    self.assertEqual(error.exception.response.status, status)
                    self.assertEqual(len(source.requests), 1)
                    self.assertEqual(target.requests, [])

    def test_raw_json_bytes_and_safe_metadata_are_archived_without_reencoding(self):
        raw = b'\xef\xbb\xbf{\r\n "DataJson": "{\\"a\\": 1}", "message": "\\u00dc"\r\n}\r\n'
        with peer(raw) as server, tempfile.TemporaryDirectory() as folder:
            client = NanoDropUltraClient(server.base_url, api_key=KEY)
            response = client.system()
            paths = client.archive(response, Path(folder) / 'evidence')
            self.assertEqual(Path(paths['body']).read_bytes(), raw)
            metadata = json.loads(Path(paths['metadata']).read_text())
            self.assertEqual(metadata['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(metadata['bytes'], len(raw))
            self.assertEqual(metadata['request_path'], '/System')
            self.assertEqual(metadata['base_url'], server.base_url)
            self.assertIn('Date', metadata['response_headers'])
            self.assertTrue(metadata['body_complete'])
            self.assertTrue(metadata['json_decoded'])
            self.assertFalse(metadata['hardware_verified'])
            self.assertNotIn(KEY, json.dumps(metadata))
            with self.assertRaises(FileExistsError):
                client.archive(response, Path(folder) / 'evidence')

    def test_malformed_and_http_error_bodies_are_retained_without_echoing_secrets(self):
        for status, error_type in [(200, ResponseFormatError), (401, HTTPResponseError)]:
            raw = ('<error>' + KEY + '</error>').encode()
            with self.subTest(status=status), peer(raw, status) as server, tempfile.TemporaryDirectory() as folder:
                client = NanoDropUltraClient(server.base_url, api_key=KEY)
                with self.assertRaises(error_type) as error:
                    client.system()
                self.assertEqual(error.exception.response.raw, raw)
                self.assertNotIn(KEY, str(error.exception))
                self.assertNotIn(KEY, json.dumps(error.exception.response.metadata))
                archive = client.archive(error.exception.response, Path(folder) / 'error-response')
                self.assertEqual(Path(archive['body']).read_bytes(), raw)

    def test_non_json_numeric_constants_are_not_silently_accepted(self):
        with peer(b'{"value":NaN}') as server:
            with self.assertRaises(ResponseFormatError) as error:
                NanoDropUltraClient(server.base_url).system()
            self.assertEqual(error.exception.response.raw, b'{"value":NaN}')

    def test_empty_204_is_not_a_fabricated_json_envelope(self):
        with peer(b'', 204) as server:
            response = NanoDropUltraClient(server.base_url).system()
            self.assertEqual(response.raw, b'')
            self.assertIsNone(response.data)
            self.assertFalse(response.json_decoded)

    def test_byte_limit_covers_both_known_and_unknown_content_lengths(self):
        for length in [True, False]:
            with self.subTest(content_length=length), peer(b'[' + b' ' * 100 + b']', send_length=length) as server:
                with self.assertRaises(ResponseTooLargeError) as error:
                    NanoDropUltraClient(server.base_url, max_response_bytes=32).system()
                self.assertIsNone(error.exception.response)

    def test_timeout_is_bounded_and_does_not_retry(self):
        with peer(delay=0.2) as server:
            started = time.monotonic()
            with self.assertRaises(NanoDropNetworkError):
                NanoDropUltraClient(server.base_url, timeout=0.04).system()
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(len(server.requests), 1)

    def test_interrupted_bodies_keep_bounded_raw_evidence_and_never_succeed(self):
        for failure in [socket.timeout(KEY), ConnectionResetError(KEY),
                        http.client.IncompleteRead(b'1', 10)]:
            with self.subTest(failure=type(failure).__name__), patch('nanodrop_ultra_network.http.client.HTTPConnection') as factory:
                incoming = factory.return_value.getresponse.return_value
                incoming.status = 200
                incoming.getheader.side_effect = lambda name: '30' if name == 'Content-Length' else None
                incoming.read1.side_effect = [b'{"value":', failure]
                client = NanoDropUltraClient('http://127.0.0.1:54011/', api_key=KEY)
                with self.assertRaises(NanoDropNetworkError) as error:
                    client.system()
                response = error.exception.response
                self.assertEqual(response.status, 200)
                self.assertFalse(response.body_complete)
                expected = b'{"value":' + (b'1' if isinstance(failure, http.client.IncompleteRead) else b'')
                self.assertEqual(response.raw, expected)
                self.assertNotIn(KEY, str(error.exception))
                with tempfile.TemporaryDirectory() as folder:
                    saved = client.archive(response, Path(folder) / 'partial')
                    self.assertEqual(Path(saved['body']).read_bytes(), expected)
                    self.assertFalse(json.loads(Path(saved['metadata']).read_text())['body_complete'])

    def test_oversized_partial_chunk_is_not_archived_as_a_complete_response(self):
        with patch('nanodrop_ultra_network.http.client.HTTPConnection') as factory:
            incoming = factory.return_value.getresponse.return_value
            incoming.status = 200
            incoming.getheader.return_value = None
            incoming.read1.side_effect = [b'12345678', http.client.IncompleteRead(b'x' * 20, 10)]
            with self.assertRaises(ResponseTooLargeError) as error:
                NanoDropUltraClient('http://127.0.0.1:54011/', max_response_bytes=16).system()
            self.assertIsNone(error.exception.response)

    def test_short_body_cannot_succeed_even_when_the_received_json_is_valid(self):
        with patch('nanodrop_ultra_network.http.client.HTTPConnection') as factory:
            incoming = factory.return_value.getresponse.return_value
            incoming.status = 200
            incoming.getheader.side_effect = lambda name: '20' if name == 'Content-Length' else None
            incoming.read1.side_effect = [b'{}', b'']
            with self.assertRaises(ResponseFormatError) as error:
                NanoDropUltraClient('http://127.0.0.1:54011/').system()
            self.assertEqual(error.exception.response.raw, b'{}')
            self.assertTrue(error.exception.response.json_decoded)
            self.assertFalse(error.exception.response.body_complete)

    def test_synthetic_marker_is_reported_as_unverified_evidence(self):
        headers = {'X-DIYLabBot-Synthetic': 'true', 'X-DIYLabBot-Model-SHA256': 'a' * 64,
                   'X-Unrelated-Secret': KEY}
        with peer(headers=headers) as server:
            response = NanoDropUltraClient(server.base_url).system()
            self.assertTrue(response.metadata['synthetic_peer_detected'])
            self.assertEqual(response.metadata['synthetic_model_sha256'], 'a' * 64)
            self.assertEqual(response.metadata['peer_evidence'], 'unverified_response_headers')
            self.assertFalse(response.metadata['hardware_verified'])
            self.assertNotIn(KEY, json.dumps(response.metadata))

    def test_response_metadata_allowlist_redacts_credential_echoes(self):
        headers = {'ETag': KEY, 'Set-Cookie': KEY, 'WWW-Authenticate': KEY,
                   'Content-Type': 'application/json', 'Last-Modified': 'Mon, 09 Nov 2026 00:00:00 GMT'}
        with peer(headers=headers) as server:
            response = NanoDropUltraClient(server.base_url, api_key=KEY).system()
            saved = response.metadata['response_headers']
            self.assertEqual(saved['ETag'], '[redacted]')
            self.assertEqual(saved['Content-Type'], 'application/json')
            self.assertNotIn('Set-Cookie', saved)
            self.assertNotIn('WWW-Authenticate', saved)
            self.assertNotIn(KEY, json.dumps(response.metadata))

    def test_https_uses_a_verified_default_ssl_context(self):
        with patch('nanodrop_ultra_network.http.client.HTTPSConnection') as factory:
            incoming = factory.return_value.getresponse.return_value
            incoming.status = 200
            incoming.getheader.return_value = None
            incoming.read1.side_effect = [b'{}', b'']
            NanoDropUltraClient('https://instrument.example:54011/').system()
            context = factory.call_args.kwargs['context']
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertEqual(factory.return_value.request.call_args.args, ('GET', '/System'))

    def test_invalid_base_urls_keys_and_limits_are_rejected_without_echoing_values(self):
        for url in ['', 'ftp://instrument/', 'http://user:' + KEY + '@instrument/',
                    'http://instrument/?x=1', 'http://instrument/#x', 'http://instrument/?',
                    'http://instrument/#', 'http://instrument/prefix/',
                    'http://instrument:99999/', 'http://instrument/\r\nX: bad']:
            with self.subTest(url=url), self.assertRaises(NanoDropNetworkError) as error:
                NanoDropUltraClient(url)
            self.assertNotIn(KEY, str(error.exception))
        for options in [{'api_key': KEY + '\r\nInjected: true'}, {'api_key': ''},
                        {'timeout': 0}, {'timeout': float('inf')}, {'timeout': True},
                        {'max_response_bytes': True}, {'max_response_bytes': 0}]:
            with self.subTest(options=list(options)), self.assertRaises(NanoDropNetworkError):
                NanoDropUltraClient('http://127.0.0.1:54011/', **options)


if __name__ == '__main__':
    unittest.main()
