"""Bounded, read-only NanoDrop Ultra HTTP reads from the pinned M024 contract.

Responses remain manufacturer data. This module does not interpret measurement
envelopes, embedded DataJson, pagination origins, sample identities or workflows.
It uses direct stdlib HTTP(S) connections: no proxy environment, retries or
redirect following. TLS uses the platform's default verified certificate store.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.parse import quote_plus, urlencode, urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/nanodrop-ultra-network.protocol.json'
FORMAT = 'solidcraftbot.nanodrop-ultra-network-protocol/1'
ENDPOINTS = {'system', 'query_experiments', 'experiment', 'experiment_detail', 'measurements'}
QUERY_TYPES = {'string', 'int32', 'int64', 'uuid', 'date-time'}
SAFE_HEADERS = ('Content-Type', 'Content-Length', 'Date', 'ETag', 'Last-Modified',
                'X-DIYLabBot-Synthetic', 'X-DIYLabBot-Model-SHA256')
RFC3339 = re.compile(r'^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$')


class NanoDropNetworkError(ValueError):
    """A sanitized request/response error; incomplete responses are not invented."""
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


class HTTPResponseError(NanoDropNetworkError):
    """HTTP failure, including a deliberately unfollowed redirect."""


class ResponseFormatError(NanoDropNetworkError):
    """A bounded response was received but was not complete valid JSON."""


class ResponseTooLargeError(NanoDropNetworkError):
    """The complete response was not retained because it exceeds the byte limit."""


def _invalid_constant(_value):
    raise ValueError('Non-JSON numeric constant')


def _load_protocol(source):
    try:
        raw = Path(source).read_bytes()
        protocol = json.loads(raw, parse_constant=_invalid_constant)
        if protocol['format'] != FORMAT or set(protocol['endpoints']) != ENDPOINTS:
            raise ValueError
        if type(protocol['default_port']) is not int or not 1 <= protocol['default_port'] <= 65535:
            raise ValueError
        for name, endpoint in protocol['endpoints'].items():
            if set(endpoint) != {'path', 'query'} or not isinstance(endpoint['query'], dict):
                raise ValueError
            path = endpoint['path']
            if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
                    or any(character in path for character in '?#!\\')
                    or any(ord(character) < 33 or ord(character) > 126 for character in path)):
                raise ValueError
            templated = name in {'experiment', 'experiment_detail'}
            if (path.count('{id}') != int(templated)
                    or '{' in path.replace('{id}', '') or '}' in path.replace('{id}', '')):
                raise ValueError
            if any(not isinstance(key, str) or kind not in QUERY_TYPES for key, kind in endpoint['query'].items()):
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise NanoDropNetworkError('Invalid NanoDrop Ultra network protocol source') from None
    return protocol, hashlib.sha256(raw).hexdigest()


def load_protocol(source=SOURCE):
    """Load the five documented read endpoint definitions, without API queries."""
    return _load_protocol(source)[0]


def _endpoint(endpoint, protocol):
    if not isinstance(endpoint, str) or endpoint not in protocol['endpoints']:
        raise NanoDropNetworkError('Unknown documented NanoDrop endpoint')
    return protocol['endpoints'][endpoint]


def _uuid(value):
    if not isinstance(value, (str, UUID)):
        raise NanoDropNetworkError('Expected a UUID string or UUID object')
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError):
        raise NanoDropNetworkError('Expected a UUID string or UUID object') from None


def endpoint_path(endpoint, id=None, *, protocol=None):
    """Resolve a documented path; callers cannot supply an arbitrary URL."""
    protocol = load_protocol() if protocol is None else protocol
    path = _endpoint(endpoint, protocol)['path']
    if '{id}' in path:
        return path.replace('{id}', _uuid(id))
    if id is not None:
        raise NanoDropNetworkError('This endpoint has no path UUID')
    return path


def validate_query(endpoint, params, *, protocol=None):
    """Validate exact field case and documented types, without page semantics.

    Integer values remain integers. Date-times are RFC 3339 strings with an
    explicit timezone; timestamp integers are never converted to/from dates.
    """
    protocol = load_protocol() if protocol is None else protocol
    contract = _endpoint(endpoint, protocol)['query']
    if not isinstance(params, dict) or set(params) - set(contract):
        raise NanoDropNetworkError('Undocumented or incorrectly cased query parameter')
    result = {}
    for key, value in params.items():
        if value is None:
            continue
        kind = contract[key]
        if kind in {'int32', 'int64'}:
            bits = int(kind[3:])
            if type(value) is not int or not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
                raise NanoDropNetworkError('Query parameter ' + key + ' requires ' + kind)
        elif kind == 'uuid':
            value = _uuid(value)
        elif kind == 'date-time':
            if not isinstance(value, str) or not RFC3339.fullmatch(value):
                raise NanoDropNetworkError('Query parameter ' + key + ' requires RFC 3339 with a timezone')
            try:
                parsed = datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError
            except ValueError:
                raise NanoDropNetworkError('Query parameter ' + key + ' requires a valid date-time') from None
        elif not isinstance(value, str):
            raise NanoDropNetworkError('Query parameter ' + key + ' requires a string')
        result[key] = value
    return result


@dataclass(frozen=True)
class Response:
    raw: bytes
    data: object
    status: int
    request_path: str
    received_at: str
    elapsed_s: float
    endpoint: str
    protocol_sha256: str
    json_decoded: bool
    origin: str
    response_headers: tuple = ()
    request_path_redacted: bool = False
    body_complete: bool = True
    synthetic_peer_detected: bool = False
    synthetic_model_sha256: str | None = None

    @property
    def metadata(self):
        """Safe archive metadata: request headers and credentials never enter it."""
        return {'format': 'solidcraftbot.nanodrop-ultra-http-response/1', 'method': 'GET',
                'origin': self.origin, 'base_url': self.origin + '/',
                'endpoint': self.endpoint, 'request_path': self.request_path, 'status': self.status,
                'request_path_redacted': self.request_path_redacted,
                'response_headers': dict(self.response_headers),
                'received_at': self.received_at, 'elapsed_s': self.elapsed_s,
                'sha256': hashlib.sha256(self.raw).hexdigest(), 'bytes': len(self.raw),
                'protocol_source_sha256': self.protocol_sha256, 'json_decoded': self.json_decoded,
                'body_complete': self.body_complete,
                'synthetic_peer_detected': self.synthetic_peer_detected,
                'synthetic_model_sha256': self.synthetic_model_sha256,
                'peer_evidence': 'unverified_response_headers' if self.synthetic_peer_detected else 'unqualified_peer',
                'hardware_verified': False,
                'workflow_imported': False}


class NanoDropUltraClient:
    def __init__(self, base_url, api_key=None, timeout=5, max_response_bytes=8 * 1024 * 1024):
        if (not isinstance(base_url, str) or any(ord(c) < 33 or ord(c) == 127 for c in base_url)):
            raise NanoDropNetworkError('Base URL must be an explicit HTTP(S) origin')
        try:
            parts = urlsplit(base_url)
            if (parts.scheme not in {'http', 'https'} or not parts.hostname
                    or parts.username is not None or parts.password is not None
                    or '?' in base_url or '#' in base_url or parts.path not in {'', '/'}):
                raise ValueError
            self._scheme, self._host, self._port = parts.scheme, parts.hostname, parts.port
        except ValueError:
            raise NanoDropNetworkError('Base URL must be an HTTP(S) origin without credentials, query or fragment') from None
        if api_key is not None and (not isinstance(api_key, str) or not api_key
                                   or any(not 33 <= ord(c) <= 126 for c in api_key)):
            raise NanoDropNetworkError('Bearer key must be a nonempty single-line ASCII token')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise NanoDropNetworkError('Timeout must be finite and positive')
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise NanoDropNetworkError('Response byte limit must be a positive integer')
        self._api_key, self.timeout, self.max_response_bytes = api_key, timeout, max_response_bytes
        self._protocol, self._protocol_sha256 = _load_protocol(SOURCE)
        host = '[' + self._host + ']' if ':' in self._host else self._host
        self._origin = self._scheme + '://' + host + (':' + str(self._port) if self._port is not None else '')

    def _redact(self, value):
        if self._api_key is not None:
            for secret in {self._api_key, quote_plus(self._api_key)}:
                value = value.replace(secret, '[redacted]')
        return value

    def system(self):
        return self._get('system')

    def query_experiments(self, **params):
        return self._get('query_experiments', params=params)

    def experiment(self, id):
        return self._get('experiment', id=id)

    def experiment_detail(self, id):
        return self._get('experiment_detail', id=id)

    def measurements(self, experiment_id=None, start_page=None, page_count=None):
        return self._get('measurements', params={key: value for key, value in [
            ('experimentId', experiment_id), ('startPage', start_page), ('pageCount', page_count)]
            if value is not None})

    def _capture(self, endpoint, path, status, observed_headers, raw, started, complete):
        parsed, decoded = None, False
        if raw:
            try:
                parsed = json.loads(raw, parse_constant=_invalid_constant)
                decoded = True
            except (ValueError, UnicodeError, RecursionError):
                pass
        marker = (observed_headers.get('X-DIYLabBot-Synthetic') or '').strip().casefold() == 'true'
        model_hash = observed_headers.get('X-DIYLabBot-Model-SHA256')
        model_hash = model_hash.lower() if marker and isinstance(model_hash, str) and re.fullmatch('[0-9a-fA-F]{64}', model_hash) else None
        if model_hash and self._redact(model_hash) != model_hash:
            model_hash = None
        safe_headers = tuple((name, self._redact(value)) for name, value in observed_headers.items())
        safe_path = self._redact(path)
        return Response(raw=raw, data=parsed, status=status, request_path=safe_path,
            received_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            elapsed_s=time.monotonic() - started, endpoint=endpoint,
            protocol_sha256=self._protocol_sha256, json_decoded=decoded,
            origin=self._origin, response_headers=safe_headers, request_path_redacted=safe_path != path,
            body_complete=complete, synthetic_peer_detected=marker, synthetic_model_sha256=model_hash)

    def _get(self, endpoint, id=None, params=None):
        path = endpoint_path(endpoint, id, protocol=self._protocol)
        query = validate_query(endpoint, {} if params is None else params, protocol=self._protocol)
        if query:
            path += '?' + urlencode(query)
        headers = {'Accept': 'application/json'}
        if self._api_key is not None:
            headers['Authorization'] = 'Bearer ' + self._api_key
        started = time.monotonic()
        connection = (http.client.HTTPSConnection(self._host, self._port, timeout=self.timeout,
                       context=ssl.create_default_context()) if self._scheme == 'https' else
                      http.client.HTTPConnection(self._host, self._port, timeout=self.timeout))
        chunks, total, status, observed_headers = [], 0, None, {}
        def captured(complete=False):
            return (None if status is None else self._capture(
                endpoint, path, status, observed_headers, b''.join(chunks), started, complete))
        try:
            connection.request('GET', path, headers=headers)
            incoming = connection.getresponse()
            status = incoming.status
            observed_headers = {name: value for name in SAFE_HEADERS
                                if isinstance(value := incoming.getheader(name), str)}
            length = observed_headers.get('Content-Length')
            expected = int(length) if length is not None and length.isdecimal() else None
            if expected is not None and expected > self.max_response_bytes:
                raise ResponseTooLargeError('Response exceeds configured byte limit')
            while True:
                if time.monotonic() - started >= self.timeout:
                    raise TimeoutError
                chunk = incoming.read1(min(65536, self.max_response_bytes - total + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise ResponseTooLargeError('Response exceeds configured byte limit')
            response = captured(complete=expected is None or expected == total)
            if not 200 <= status < 300:
                raise HTTPResponseError('HTTP status ' + str(status) + ' for ' + response.request_path, response)
            if not response.body_complete:
                raise ResponseFormatError('Incomplete NanoDrop HTTP response body', response)
            if not response.json_decoded and not (status == 204 and not response.raw):
                raise ResponseFormatError('NanoDrop HTTP response is not valid JSON', response)
            return response
        except NanoDropNetworkError:
            raise
        except http.client.IncompleteRead as error:
            partial = error.partial if isinstance(error.partial, bytes) else b''
            if total + len(partial) > self.max_response_bytes:
                raise ResponseTooLargeError('Response exceeds configured byte limit') from None
            chunks.append(partial)
            raise ResponseFormatError('Incomplete NanoDrop HTTP response body', captured()) from None
        except (socket.timeout, TimeoutError):
            raise NanoDropNetworkError('NanoDrop HTTP request timed out', captured()) from None
        except (OSError, http.client.HTTPException, ValueError, UnicodeError):
            # Do not echo server reason phrases, response bodies or request headers.
            raise NanoDropNetworkError('NanoDrop HTTP connection or response failed', captured()) from None
        finally:
            connection.close()

    def archive(self, response, destination):
        """Create one new evidence directory; never overwrite existing archives."""
        if not isinstance(response, Response):
            raise NanoDropNetworkError('A captured NanoDrop response is required')
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=False)
        body, metadata = target / 'response.bin', target / 'metadata.json'
        body.write_bytes(response.raw)
        metadata.write_text(json.dumps(response.metadata, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        return {'body': str(body), 'metadata': str(metadata), 'sha256': response.metadata['sha256']}
