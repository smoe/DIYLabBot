"""Real loopback TLS framing checks; core role/ledger tests live separately.

The small fake service here deliberately owns no workflow or inventory. These
tests qualify HTTP/TLS boundaries and lack of implicit client retries only.
"""
import base64
from contextlib import redirect_stderr
import copy
from datetime import datetime, timedelta, timezone
import http.client
import io
import json
from pathlib import Path
import secrets
import socket
import ssl
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import lab_transport_http as transport_http
from lab_transport_http import TransportClient, TransportHTTPError, TransportHTTPServer, tls_identity


class _Access:
    def __init__(self, server_uuid):
        self.server_uuid = server_uuid
        self.tokens = {}

    def login(self, username, password, server_uuid):
        if (username not in {'owner', 'observer'} or password != 'synthetic-http-password'
                or server_uuid != self.server_uuid):
            raise PermissionError('Do not reflect submitted credentials')
        token = secrets.token_urlsafe(32)
        self.tokens[token] = {'subject': username, 'principal': 'P.' + username,
                              'grants': [{'id': username, 'kind': username, 'resource_id': 'Run'}]}
        return {'access_token': token, 'token_type': 'Bearer', 'expires_in_s': 900,
                'subject': username, 'server_uuid': server_uuid}

    def authorize(self, token):
        if token not in self.tokens:
            raise PermissionError('Internal rejected token: ' + token)
        return copy.deepcopy(self.tokens[token])

    def logout(self, token):
        self.authorize(token)
        self.tokens.pop(token)


class _Service:
    server_uuid = 'SYN.HTTP.Server'
    boot_id = 'SYN.HTTP.Boot01'
    run_id = 'SYN.HTTP.Run'

    def __init__(self):
        self.access = _Access(self.server_uuid)
        self.calls = []
        self.receipts = {}

    def info(self):
        self.calls.append(('info',))
        return {'format': 'solidcraftbot.lab-transport-network-info/1',
                'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
                'run_id': self.run_id, 'mode': 'synthetic_only', 'tls_required': True}

    def session(self, context):
        self.calls.append(('session', context))
        return {**self.info(), **context}

    def snapshot(self, context, run_id, cursor=None):
        self.calls.append(('snapshot', context, run_id, cursor))
        return {'run_id': run_id, 'jobs': [], 'cursor': {'server_uuid': self.server_uuid,
                'run_id': run_id, 'sequence': 1, 'sha256': 'a' * 64}}

    def request(self, context, run_id, request_id, operation, args, wire_bytes,
                grant_id=None, cursor=None, transport_channel=None):
        self.calls.append(('request', context, run_id, request_id, operation,
                           args, wire_bytes, grant_id, cursor, transport_channel))
        if context['subject'] != 'owner':
            raise PermissionError('INTERNAL_AUTH_DETAIL')
        key = (context['subject'], request_id)
        replayed = key in self.receipts
        self.receipts.setdefault(key, {'request_id': request_id, 'principal': context['principal'],
                                       'response': {'accepted': True}})
        return {'receipt': self.receipts[key], 'replayed': replayed, 'snapshot': {'jobs': []}}

    def receipt(self, context, run_id, request_id, cursor=None):
        self.calls.append(('receipt', context, run_id, request_id, cursor))
        return {'receipt': self.receipts.get((context['subject'], request_id)),
                'replayed': True, 'snapshot': {'jobs': []}}


class CourierHTTPTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='courier-http-test-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.ui = self.folder / 'ui'; self.ui.mkdir()
        for name in ('lab_transport_courier.html', 'lab_transport_courier.js', 'lab_transport_courier.css'):
            (self.ui / name).write_text('/* synthetic HTTP framing fixture */')
        self.protocol = {'paths': {'info': '/api/info', 'login': '/api/login', 'logout': '/api/logout',
                        'session': '/api/session', 'snapshot': '/api/snapshot',
                        'requests': '/api/requests', 'receipt_prefix': '/api/requests/'},
                         'limits': {'max_body_bytes': 65536, 'max_response_bytes': 2097152,
                                    'request_timeout_s': 2}}
        self.contract_patch = patch.object(transport_http, '_contract', lambda: copy.deepcopy(self.protocol))
        self.contract_patch.start(); self.addCleanup(self.contract_patch.stop)
        self.service = _Service()
        self.server = TransportHTTPServer(self.service, self.folder / 'tls', ui_directory=self.ui)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.client = TransportClient(self.server.origin, self.server.certificate_path)

    def stop(self):
        self.server.shutdown(); self.thread.join(5); self.server.server_close()

    def login(self, username='owner'):
        return self.client.login(username, 'synthetic-http-password', self.service.server_uuid)

    def raw(self, method, path, raw=None, headers=None):
        context = ssl.create_default_context(cafile=str(self.server.certificate_path))
        connection = http.client.HTTPSConnection('127.0.0.1', self.server.server_port, context=context, timeout=3)
        supplied = {} if headers is None else dict(headers)
        connection.request(method, path, body=raw, headers=supplied)
        response = connection.getresponse(); data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def test_verified_tls_public_info_and_exact_static_assets_have_security_headers(self):
        self.assertEqual(self.client.info()['server_uuid'], self.service.server_uuid)
        for path in ('/', '/courier.js', '/courier.css'):
            status, headers, _ = self.raw('GET', path)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin', headers)
        status, _, _ = self.raw('GET', '/../../AGENTS.md')
        self.assertNotEqual(status, 200)
        self.assertFalse(self.service.receipts)

    def test_login_logout_and_expired_token_are_sanitized_and_have_no_root_effect(self):
        with self.assertRaises(TransportHTTPError) as wrong:
            self.client.login('owner', 'secret-reflection-test', self.service.server_uuid)
        self.assertEqual(wrong.exception.status, 401)
        self.assertNotIn('secret-reflection-test', str(wrong.exception))
        result = self.login(); token = result['access_token']
        self.assertEqual(self.client.session()['subject'], 'owner')
        self.client.logout()
        self.assertNotIn(token, self.service.access.tokens)
        with self.assertRaises(TransportHTTPError) as denied: self.client.snapshot()
        self.assertEqual(denied.exception.status, 401)
        result = self.login(); self.service.access.tokens.clear()
        with self.assertRaises(TransportHTTPError) as expired: self.client.snapshot()
        self.assertEqual(expired.exception.status, 401)
        self.assertNotIn(result['access_token'], str(expired.exception))
        self.assertFalse(self.service.receipts)

    def test_post_derives_context_from_token_and_preserves_only_original_body_bytes(self):
        auth = self.login()
        result = self.client.submit('Request01', 'owner', 'dispatch', {'job_id': 'Job01'})
        self.assertFalse(result['replayed'])
        call = next(c for c in self.service.calls if c[0] == 'request')
        self.assertEqual(call[1]['principal'], 'P.owner')
        self.assertEqual(call[-1], 'https')
        self.assertNotIn(auth['access_token'].encode(), call[6])
        self.assertEqual(json.loads(call[6]), {'request_id': 'Request01', 'grant_id': 'owner',
                                             'operation': 'dispatch', 'args': {'job_id': 'Job01'}})
        before = len([c for c in self.service.calls if c[0] == 'request'])
        bad = json.dumps({'request_id': 'Request02', 'grant_id': 'owner', 'operation': 'dispatch',
                          'args': {}, 'principal': 'P.owner'}).encode()
        status, _, _ = self.raw('POST', '/api/requests', bad,
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + auth['access_token']})
        self.assertEqual(status, 400)
        self.assertEqual(len([c for c in self.service.calls if c[0] == 'request']), before)

    def test_role_rejection_is_403_without_internal_details(self):
        self.login('observer')
        with self.assertRaises(TransportHTTPError) as denied:
            self.client.submit('Request01', 'observer', 'dispatch', {})
        self.assertEqual(denied.exception.status, 403)
        self.assertNotIn('INTERNAL_AUTH_DETAIL', str(denied.exception))
        self.assertFalse(self.service.receipts)

    def test_failed_reauthentication_does_not_keep_another_users_cached_token(self):
        owner_token = self.login()['access_token']
        with self.assertRaises(TransportHTTPError):
            self.client.login('observer', 'incorrect-password', self.service.server_uuid)
        with self.assertRaises(TransportHTTPError) as denied: self.client.session()
        self.assertEqual(denied.exception.status, 401)
        self.assertIn(owner_token, self.service.access.tokens)
        self.assertFalse(self.service.receipts)

    def test_context_expiry_after_header_authentication_remains_a_401(self):
        self.login()
        class ExpiredContext(PermissionError):
            status = 401
        def expired(*args, **kwargs):
            raise ExpiredContext('Internal context detail must not be returned')
        self.service.request = expired
        with self.assertRaises(TransportHTTPError) as denied:
            self.client.submit('Expired01', 'owner', 'dispatch', {})
        self.assertEqual(denied.exception.status, 401)
        self.assertNotIn('Internal context', str(denied.exception))
        self.assertFalse(self.service.receipts)

    def test_duplicate_json_nonfinite_values_and_body_limits_are_rejected(self):
        auth = self.login()
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + auth['access_token']}
        for raw in (b'{"request_id":"A","request_id":"B"}', b'{"x":NaN}', b'not-json'):
            self.assertEqual(self.raw('POST', '/api/requests', raw, headers)[0], 400)
        self.assertEqual(self.raw('POST', '/api/requests', b'',
            {**headers, 'Content-Length': '65537'})[0], 413)
        self.assertEqual(self.raw('POST', '/api/requests', b'{}',
            {**headers, 'Content-Type': 'text/plain'})[0], 415)
        self.assertFalse(self.service.receipts)

    def test_ambiguous_headers_transfer_encoding_origin_and_host_fail_closed(self):
        auth = self.login()
        for duplicate in ('Authorization', 'Content-Length', 'Content-Type', 'Origin', 'Host'):
            with self.subTest(header=duplicate):
                connection = http.client.HTTPSConnection('127.0.0.1', self.server.server_port,
                    context=ssl.create_default_context(cafile=str(self.server.certificate_path)), timeout=3)
                connection.putrequest('POST', '/api/logout')
                values = {'Authorization': 'Bearer ' + auth['access_token'], 'Content-Length': '2',
                          'Content-Type': 'application/json', 'Origin': self.server.origin}
                for name, value in values.items(): connection.putheader(name, value)
                connection.putheader(duplicate, values.get(duplicate, 'localhost:' + str(self.server.server_port)))
                connection.endheaders(b'{}')
                response = connection.getresponse(); response.read()
                self.assertEqual(response.status, 400); connection.close()
        self.assertEqual(self.raw('GET', '/api/info', headers={'Host': 'evil.example'})[0], 400)
        self.assertEqual(self.raw('GET', '/api/info', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.raw('POST', '/api/logout', b'',
            {'Transfer-Encoding': 'chunked', 'Content-Type': 'application/json'})[0], 400)
        status, headers, _ = self.raw('OPTIONS', '/api/requests')
        self.assertEqual(status, 405); self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertIn(auth['access_token'], self.service.access.tokens)

    def test_cursor_object_is_encoded_without_changing_its_content(self):
        self.login(); snapshot = self.client.snapshot()
        self.client.snapshot(cursor=snapshot['cursor'])
        call = [c for c in self.service.calls if c[0] == 'snapshot'][-1]
        decoded = json.loads(base64.urlsafe_b64decode(call[-1] + '=' * (-len(call[-1]) % 4)))
        self.assertEqual(decoded, snapshot['cursor'])
        self.assertFalse(self.service.receipts)

    def test_lost_mutation_reply_does_not_retry_or_invent_a_new_identifier(self):
        self.login()
        original = transport_http._Handler._respond
        def lose_response(handler, status, value, content_type='application/json; charset=utf-8'):
            if handler.path == '/api/requests' and status == 200:
                handler.connection.shutdown(socket.SHUT_RDWR); handler.connection.close(); return
            return original(handler, status, value, content_type)
        with patch.object(transport_http._Handler, '_respond', lose_response):
            with self.assertRaises(TransportHTTPError):
                self.client.submit('Uncertain01', 'owner', 'dispatch', {'job_id': 'Job01'})
        self.assertEqual(len([c for c in self.service.calls if c[0] == 'request']), 1)
        receipt = self.client.receipt('Uncertain01')
        self.assertEqual(receipt['receipt']['request_id'], 'Uncertain01')
        self.assertEqual(len([c for c in self.service.calls if c[0] == 'request']), 1)

    def test_client_rejects_untrusted_ca_and_wrong_hostname_without_plaintext_fallback(self):
        other, _ = tls_identity(self.folder / 'other-tls', 'SYN.Other.Server')
        untrusted = TransportClient(self.server.origin, other)
        with self.assertRaises(TransportHTTPError): untrusted.info()
        client = TransportClient('https://wrong-name.invalid:' + str(self.server.server_port), self.server.certificate_path)
        original = socket.getaddrinfo
        def resolve(host, port, *args, **kwargs):
            return original('127.0.0.1' if host == 'wrong-name.invalid' else host, port, *args, **kwargs)
        with patch.object(socket, 'getaddrinfo', resolve):
            with self.assertRaises(TransportHTTPError): client.info()
        self.assertEqual(client.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(client.context.check_hostname)
        self.assertFalse(self.service.calls)
        with self.assertRaises(ValueError): TransportClient(self.server.origin.replace('https:', 'http:'), other)

    def test_redirects_are_not_followed_and_proxy_environment_is_ignored(self):
        calls = []
        def redirect(handler):
            calls.append(handler.path)
            handler._respond(302, {'error': {'code': 'Redirected', 'message': 'not followed'}})
        with patch.object(transport_http._Handler, 'do_GET', redirect):
            with self.assertRaises(TransportHTTPError) as error: self.client.info()
        self.assertEqual(error.exception.status, 302)
        self.assertEqual(calls, ['/api/info'])
        with patch.dict('os.environ', {'HTTPS_PROXY': 'http://unreachable.invalid:1', 'https_proxy': 'http://unreachable.invalid:1'}):
            self.assertEqual(self.client.info()['server_uuid'], self.service.server_uuid)

    def test_a_tcp_peer_without_tls_handshake_does_not_block_other_clients(self):
        connection = socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2)
        try:
            self.assertEqual(self.client.info()['server_uuid'], self.service.server_uuid)
        finally:
            connection.close()

    def test_identity_is_persistent_private_and_never_replaced_on_mismatch(self):
        certificate = self.server.certificate_path.read_bytes()
        key_path = self.folder / 'tls/server.key'
        self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
        self.assertEqual(tls_identity(self.folder / 'tls', self.service.server_uuid)[0].read_bytes(), certificate)
        with self.assertRaisesRegex(ValueError, 'another server'):
            tls_identity(self.folder / 'tls', 'SYN.Wrong.Server')
        self.assertEqual(self.server.certificate_path.read_bytes(), certificate)
        key_path.unlink()
        with self.assertRaisesRegex(ValueError, 'Incomplete'): tls_identity(self.folder / 'tls', self.service.server_uuid)
        self.assertEqual(self.server.certificate_path.read_bytes(), certificate)

    def test_tls_pairing_san_and_validity_are_checked_before_server_start(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        key_path = self.folder / 'tls/server.key'
        original = self.server.certificate_path.read_bytes()
        certificate = x509.load_pem_x509_certificate(original)
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        now = datetime.now(timezone.utc)
        for label, start, end, sans in [
            ('expired', now - timedelta(days=2), now - timedelta(days=1),
             [x509.DNSName('localhost'), x509.IPAddress(__import__('ipaddress').ip_address('127.0.0.1'))]),
            ('future', now + timedelta(days=1), now + timedelta(days=2),
             [x509.DNSName('localhost'), x509.IPAddress(__import__('ipaddress').ip_address('127.0.0.1'))]),
            ('missing-loopback-ip', now - timedelta(minutes=1), now + timedelta(days=1),
             [x509.DNSName('localhost')])]:
            with self.subTest(label=label):
                invalid = (x509.CertificateBuilder().subject_name(certificate.subject)
                    .issuer_name(certificate.issuer).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(start).not_valid_after(end)
                    .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                    .sign(key, certificate.signature_hash_algorithm).public_bytes(serialization.Encoding.PEM))
                self.server.certificate_path.write_bytes(invalid)
                with self.assertRaises(ValueError): tls_identity(self.folder / 'tls', self.service.server_uuid)
                self.assertEqual(self.server.certificate_path.read_bytes(), invalid)
        self.server.certificate_path.write_bytes(original)
        _, other_key = tls_identity(self.folder / 'different-key', 'SYN.Other.Server')
        key_path.write_bytes(other_key.read_bytes())
        with self.assertRaisesRegex(ValueError, 'do not match'):
            tls_identity(self.folder / 'tls', self.service.server_uuid)
        self.assertEqual(self.server.certificate_path.read_bytes(), original)

    def test_response_byte_limits_apply_at_server_and_client(self):
        bounded = TransportClient(self.server.origin, self.server.certificate_path, max_response_bytes=32)
        with self.assertRaises(TransportHTTPError) as large: bounded.info()
        self.assertEqual(large.exception.code, 'ResponseTooLarge')
        self.service.info = lambda: {'oversized': 'x' * (self.protocol['limits']['max_response_bytes'] + 1)}
        with self.assertRaises(TransportHTTPError) as rejected: self.client.info()
        self.assertEqual(rejected.exception.status, 503)
        self.assertEqual(rejected.exception.code, 'ResponseTooLarge')

    def test_client_origins_and_literal_api_paths_do_not_rewrite_invalid_urls(self):
        for url in ('https://localhost:0', self.server.origin + '?', self.server.origin + '#',
                    self.server.origin + '/other', 'https://user:secret@localhost',
                    'https://localhost:not-a-port', 'https://localhost/\x7f'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                TransportClient(url, self.server.certificate_path)
        for path in ('/api/info?', '/api/info#', '/api/%69nfo'):
            self.assertEqual(self.raw('GET', path)[0], 400)

    def test_credentials_are_not_reflected_in_errors_or_default_server_logs(self):
        token = self.login()['access_token']
        captured = io.StringIO()
        with redirect_stderr(captured):
            status, _, raw = self.raw('GET', '/api/info?access_token=' + token)
            self.assertEqual(status, 400)
            self.assertNotIn(token.encode(), raw)
            status, _, raw = self.raw('GET', '/api/session',
                                     headers={'Authorization': 'Bearer InvalidCredentialSecret123'})
            self.assertEqual(status, 401)
            self.assertNotIn(b'InvalidCredentialSecret123', raw)
        self.assertEqual(captured.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
