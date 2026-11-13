"""Bounded same-origin HTTPS transport for the synthetic T3 courier service.

Authentication is delegated to the service access controller. No HTTP payload
supplies its own principal, and this module never executes instrument or robot
operations. A connection failure never retries a mutating request.
"""
from datetime import datetime, timedelta, timezone
import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import stat
from urllib.parse import urlsplit

from manual_tasks import TaskError

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {'/': ('lab_transport_courier.html', 'text/html; charset=utf-8'),
          '/courier.js': ('lab_transport_courier.js', 'application/javascript; charset=utf-8'),
          '/courier.css': ('lab_transport_courier.css', 'text/css; charset=utf-8')}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    def invalid(_value):
        raise ValueError('Nonfinite JSON constant')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def _exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError('Exact request fields required')


def _contract():
    from lab_transport_network_sources import load_contract
    return load_contract()


def tls_identity(directory, server_uuid):
    """Create once, or validate the same private loopback TLS identity.

    Cryptography is an existing locked project dependency. No SiLA SDK or
    feature certificate is involved. Incomplete, expired or mismatched files
    require explicit repair; they are never replaced automatically.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    if not isinstance(server_uuid, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', server_uuid):
        raise ValueError('Stable server identity required')
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    cert_path, key_path = directory / 'server.crt', directory / 'server.key'
    if cert_path.exists() != key_path.exists():
        raise ValueError('Incomplete courier TLS identity; explicit repair required')
    if not cert_path.exists():
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'DIYLabBot courier service'),
                             x509.NameAttribute(NameOID.SERIAL_NUMBER, server_uuid)])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(private_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(private_key, hashes.SHA256()))
        key = private_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cert = certificate.public_bytes(serialization.Encoding.PEM)
        for path, content in ((key_path, key), (cert_path, cert)):
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'wb') as output:
                output.write(content); output.flush(); os.fsync(output.fileno())
    if os.name != 'nt' and stat.S_IMODE(key_path.stat().st_mode) & 0o077:
        raise ValueError('Courier TLS private key must not be group/world accessible')
    cert, key = cert_path.read_bytes(), key_path.read_bytes()
    certificate = x509.load_pem_x509_certificate(cert)
    private_key = serialization.load_pem_private_key(key, password=None)
    serial = certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    if len(serial) != 1 or serial[0].value != server_uuid:
        raise ValueError('Courier TLS certificate belongs to another server identity')
    encoding = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if certificate.public_key().public_bytes(*encoding) != private_key.public_key().public_bytes(*encoding):
        raise ValueError('Courier TLS certificate and private key do not match')
    now = datetime.now(timezone.utc)
    if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc:
        raise ValueError('Courier TLS certificate requires explicit renewal')
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if ('localhost' not in names.get_values_for_type(x509.DNSName)
            or ipaddress.ip_address('127.0.0.1') not in names.get_values_for_type(x509.IPAddress)):
        raise ValueError('Courier TLS certificate must cover both loopback names')
    return cert_path, key_path


class _HTTPFailure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class TransportHTTPServer(ThreadingHTTPServer):
    """Loopback TLS boundary; each service call uses its own journal connection."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, service, certificate_directory, host='127.0.0.1', port=0, ui_directory=None):
        if host not in {'127.0.0.1', 'localhost'}:
            raise ValueError('Courier HTTP currently supports loopback hosts only')
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Valid courier HTTP port required')
        self.service = service
        self.contract = _contract()
        self.certificate_path, key = tls_identity(certificate_directory, service.server_uuid)
        directory = ROOT / 'scripts' if ui_directory is None else Path(ui_directory)
        self.assets = {url: ((directory / name).read_bytes(), content_type)
                       for url, (name, content_type) in ASSETS.items()}
        super().__init__((host, port), _Handler)
        self.origin = 'https://' + host + ':' + str(self.server_port)
        suffix = '' if self.server_port == 443 else ':' + str(self.server_port)
        self.allowed_hosts = {name + suffix for name in ('127.0.0.1', 'localhost')}
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            context.load_cert_chain(self.certificate_path, key)
            # Handshakes happen in bounded handler threads, so a peer that only
            # opens TCP cannot block every other authenticated client.
            self.socket = context.wrap_socket(self.socket, server_side=True,
                                              do_handshake_on_connect=False)
        except BaseException:
            self.server_close()
            raise

    def handle_error(self, request, client_address):
        # Default socketserver tracebacks can contain submitted request values.
        pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'DIYLabBotCourier'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.contract['limits']['request_timeout_s'])

    def log_message(self, *unused):
        pass

    def _respond(self, status, value, content_type='application/json; charset=utf-8'):
        raw = value if isinstance(value, bytes) else _encoded(value)
        if len(raw) > self.server.contract['limits']['max_response_bytes']:
            status, content_type = 503, 'application/json; charset=utf-8'
            raw = _encoded({'error': {'code': 'ResponseTooLarge',
                                     'message': 'Response exceeds the byte limit'}})
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Connection', 'close')
        if status == 401:
            self.send_header('WWW-Authenticate', 'Bearer realm="DIYLabBot courier"')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(raw)

    def _error(self, status, code):
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}', code):
            code = 'RequestRejected'
        message = {400: 'Malformed request', 401: 'Authentication required',
                   403: 'Operation not permitted', 404: 'Resource not available',
                   405: 'Method not supported', 409: 'Request conflicts with current state',
                   413: 'Request exceeds the byte limit', 415: 'JSON content type required',
                   503: 'Service temporarily unavailable'}.get(status, 'Service operation failed')
        self._respond(status, {'error': {'code': code, 'message': message}})

    def send_error(self, code, message=None, explain=None):
        # Also sanitize parser-level errors rather than reflecting request lines.
        self._error(code if 400 <= code <= 599 else 400, 'RequestRejected')

    def _boundary(self):
        for name in ('Host', 'Authorization', 'Content-Length', 'Content-Type', 'Origin', 'X-Lab-Cursor'):
            if len(self.headers.get_all(name, [])) > 1:
                raise _HTTPFailure(400, 'DuplicateHeader')
        host = self.headers.get('Host')
        if host not in self.server.allowed_hosts:
            raise _HTTPFailure(400, 'InvalidHost')
        origin = self.headers.get('Origin')
        if origin is not None and origin != 'https://' + host:
            raise _HTTPFailure(403, 'InvalidOrigin')
        if self.headers.get('Transfer-Encoding') is not None:
            raise _HTTPFailure(400, 'UnsupportedTransferEncoding')
        parts = urlsplit(self.path)
        if (parts.scheme or parts.netloc or '?' in self.path or '#' in self.path
                or '%' in parts.path):
            raise _HTTPFailure(400, 'InvalidPath')
        return parts.path

    def _body(self):
        value = self.headers.get('Content-Length')
        if value is None or not re.fullmatch(r'[0-9]+', value):
            raise _HTTPFailure(400, 'ContentLengthRequired')
        length = int(value)
        if length > self.server.contract['limits']['max_body_bytes']:
            raise _HTTPFailure(413, 'RequestTooLarge')
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise _HTTPFailure(415, 'JSONRequired')
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise _HTTPFailure(400, 'IncompleteBody')
        return raw, _json(raw)

    def _context(self):
        header = self.headers.get('Authorization', '')
        if not re.fullmatch(r'Bearer [A-Za-z0-9._~-]{1,512}', header):
            raise _HTTPFailure(401, 'InvalidAccessToken')
        token = header[7:]
        try:
            return token, self.server.service.access.authorize(token)
        except PermissionError:
            raise _HTTPFailure(401, 'InvalidAccessToken') from None

    def _dispatch(self, method):
        try:
            path = self._boundary()
            service = self.server.service
            paths = self.server.contract['paths']
            if method == 'GET' and path in self.server.assets:
                raw, content_type = self.server.assets[path]
                self._respond(200, raw, content_type)
                return
            if method == 'GET' and path == paths['info']:
                self._respond(200, service.info())
                return
            if method == 'POST':
                raw, body = self._body()
                if path == paths['login']:
                    _exact(body, 'username password server_uuid')
                    try:
                        result = service.access.login(body['username'], body['password'], body['server_uuid'])
                    except PermissionError:
                        raise _HTTPFailure(401, 'AuthenticationFailed') from None
                    self._respond(200, result)
                    return
            token, context = self._context()
            cursor = self.headers.get('X-Lab-Cursor')
            if cursor is not None and (len(cursor) > 2048 or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', cursor)):
                raise _HTTPFailure(400, 'InvalidCursor')
            if method == 'GET' and path == paths['session']:
                result = service.session(context)
            elif method == 'GET' and path == paths['snapshot']:
                result = service.snapshot(context, service.run_id, cursor=cursor)
            elif method == 'GET' and path.startswith(paths['receipt_prefix']):
                request_id = path[len(paths['receipt_prefix']):]
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', request_id):
                    raise _HTTPFailure(400, 'InvalidRequestId')
                result = service.receipt(context, service.run_id, request_id, cursor=cursor)
            elif method == 'POST' and path == paths['logout']:
                _exact(body, '')
                service.access.logout(token)
                result = {'logged_out': True}
            elif method == 'POST' and path == paths['requests']:
                _exact(body, 'request_id grant_id operation args')
                result = service.request(context, service.run_id, body['request_id'],
                    body['operation'], body['args'], raw, grant_id=body['grant_id'],
                    cursor=cursor, transport_channel='https')
            else:
                raise _HTTPFailure(404, 'NotFound')
            self._respond(200, result)
        except _HTTPFailure as error:
            self._error(error.status, error.code)
        except PermissionError as error:
            status = 401 if getattr(error, 'status', 403) == 401 else 403
            self._error(status, 'InvalidAccessToken' if status == 401 else 'OperationNotPermitted')
        except TaskError as error:
            status = getattr(error, 'status', 409)
            self._error(status if status in {400, 403, 404, 409, 422, 503} else 409,
                        getattr(error, 'code', 'WorkflowRejected'))
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            self._error(400, 'MalformedRequest')
        except (socket.timeout, OSError):
            self._error(503, 'ServiceUnavailable')
        except Exception:
            self._error(500, 'ServiceFailure')

    def do_GET(self): self._dispatch('GET')
    def do_POST(self): self._dispatch('POST')
    def do_OPTIONS(self): self._error(405, 'MethodNotSupported')
    def do_PUT(self): self._error(405, 'MethodNotSupported')
    def do_DELETE(self): self._error(405, 'MethodNotSupported')
    def do_PATCH(self): self._error(405, 'MethodNotSupported')


class TransportHTTPError(ValueError):
    """Sanitized client failure. Transport uncertainty never triggers a retry."""
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__('Courier request failed: ' + code)


class TransportClient:
    def __init__(self, base_url, certificate, timeout=None, max_response_bytes=None):
        self.contract = _contract()
        self.paths = self.contract['paths']
        timeout = self.contract['limits']['request_timeout_s'] if timeout is None else timeout
        max_response_bytes = (self.contract['limits']['max_response_bytes']
                              if max_response_bytes is None else max_response_bytes)
        if not isinstance(base_url, str):
            raise ValueError('An explicit HTTPS origin without credentials is required')
        try:
            parts = urlsplit(base_url)
            port = 443 if parts.port is None else parts.port
            if not 1 <= port <= 65535: raise ValueError
        except ValueError:
            raise ValueError('An explicit HTTPS origin without credentials is required') from None
        if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.path not in {'', '/'}
                or '?' in base_url or '#' in base_url
                or any(ord(c) < 33 or ord(c) == 127 for c in base_url)):
            raise ValueError('An explicit HTTPS origin without credentials is required')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Finite positive timeout required')
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError('Positive response byte limit required')
        self.host, self.port = parts.hostname, port
        self.origin = 'https://' + self.host + (':' + str(parts.port) if parts.port is not None else '')
        self.timeout, self.max_response_bytes = timeout, max_response_bytes
        self.context = ssl.create_default_context(cafile=str(certificate))
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._token = None

    def _request(self, method, path, value=None, token=None, cursor=None):
        headers = {'Accept': 'application/json'}
        if token is not None:
            if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{1,512}', token):
                raise ValueError('Single-line bearer token required')
            headers['Authorization'] = 'Bearer ' + token
        if cursor is not None:
            if isinstance(cursor, dict):
                cursor = base64.urlsafe_b64encode(_encoded(cursor)).decode().rstrip('=')
            if not isinstance(cursor, str) or len(cursor) > 2048 or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', cursor):
                raise ValueError('Opaque snapshot cursor required')
            headers['X-Lab-Cursor'] = cursor
        body = None if value is None else _encoded(value)
        if body is not None:
            if len(body) > self.contract['limits']['max_body_bytes']: raise ValueError('Request exceeds byte limit')
            headers.update({'Content-Type': 'application/json', 'Origin': self.origin})
        connection = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self.context)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(self.max_response_bytes + 1)
            if len(raw) > self.max_response_bytes:
                raise TransportHTTPError('ResponseTooLarge', response.status)
            if response.status != 200:
                # Never follow redirects or include remote bodies/URLs/secrets.
                code = 'HTTPRejected'
                try:
                    candidate = _json(raw).get('error', {}).get('code')
                    if isinstance(candidate, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}', candidate):
                        secrets = [token, self._token]
                        if isinstance(value, dict): secrets.append(value.get('password'))
                        if not any(isinstance(secret, str) and secret and secret in candidate for secret in secrets):
                            code = candidate
                except (ValueError, AttributeError, TypeError):
                    pass
                raise TransportHTTPError(code, response.status)
            if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise TransportHTTPError('InvalidContentType', response.status)
            return _json(raw)
        except TransportHTTPError:
            raise
        except (OSError, ValueError, http.client.HTTPException, RecursionError):
            raise TransportHTTPError('ConnectionOrResponseFailure') from None
        finally:
            connection.close()

    def info(self): return self._request('GET', self.paths['info'])

    def login(self, username, password, server_uuid):
        self._token = None
        result = self._request('POST', self.paths['login'], {'username': username, 'password': password,
                                                      'server_uuid': server_uuid})
        token = result.get('access_token') if isinstance(result, dict) else None
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{1,512}', token):
            raise TransportHTTPError('InvalidAuthenticationResponse')
        self._token = token
        return result

    def logout(self):
        try: return self._request('POST', self.paths['logout'], {}, token=self._token)
        finally: self._token = None

    def session(self): return self._request('GET', self.paths['session'], token=self._token)
    def snapshot(self, cursor=None): return self._request('GET', self.paths['snapshot'], token=self._token, cursor=cursor)

    def receipt(self, request_id, cursor=None):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', request_id):
            raise ValueError('Explicit request identifier required')
        return self._request('GET', self.paths['receipt_prefix'] + request_id, token=self._token, cursor=cursor)

    def submit(self, request_id, grant_id, operation, args, cursor=None):
        return self._request('POST', self.paths['requests'], {'request_id': request_id, 'grant_id': grant_id,
                             'operation': operation, 'args': args}, token=self._token, cursor=cursor)
