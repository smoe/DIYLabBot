"""Synthetic UltraC HTTP read interface; no instrument or workflow side effects."""
import copy
import hashlib
import hmac
import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from nanodrop_ultra_network import load_protocol, validate_query

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/nanodrop-ultra-network.synthetic.json'


def _date(value):
    parsed = datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('A date-time needs a timezone')
    return parsed


def load_model(source=SOURCE):
    """Resolve pinned catalog/protocol once; keep responses independent of CAD."""
    source = Path(source).resolve()
    raw = source.read_bytes()
    model = json.loads(raw)
    if model.get('format') != 'solidcraftbot.nanodrop-ultra-network-model/1' or model.get('synthetic') is not True:
        raise ValueError('Expected a versioned, explicitly synthetic UltraC network model')
    references = {}
    for key in ('catalog', 'protocol'):
        reference = model[key]
        path = (ROOT / reference['path']).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != reference['sha256']:
            raise ValueError(f'Invalid {key} source reference')
        references[key] = path
    catalog = json.loads(references['catalog'].read_bytes())
    if model['instrument_type'] != 'nanodrop_ultrac' or model['instrument_type'] not in catalog['types']:
        raise ValueError('This interface is bound to the UltraC catalog type only')
    protocol = load_protocol(references['protocol'])
    semantics = model['synthetic_semantics']
    expected = {'experiment_page_origin': 0, 'measurement_page_origin': 0,
                'timestamp_unit': 'unix_milliseconds', 'name_filter': 'casefold_substring',
                'application_filter': 'casefold_exact'}
    if any(semantics.get(key) != value for key, value in expected.items()):
        raise ValueError('Unsupported synthetic query semantics')
    for key in ('experiment_default_page_size', 'measurement_page_size'):
        if type(semantics[key]) is not int or semantics[key] <= 0:
            raise ValueError('Synthetic page sizes must be positive integers')
    experiment_ids = set()
    for record in model['experiments']:
        identifier = str(UUID(record['Id']))
        if identifier != record['Id'] or identifier in experiment_ids:
            raise ValueError('Experiment IDs must be unique canonical UUIDs')
        experiment_ids.add(identifier)
        _date(record['CreatedTime'])
        if not all(isinstance(record[key], str) for key in ('Name', 'Application')):
            raise ValueError('Invalid synthetic experiment')
    measurement_ids = set()
    for record in model['measurements']:
        if set(record) != set(protocol['measurement_fields']):
            raise ValueError('Measurement fields must match the documented field set')
        for key, kind in protocol['measurement_fields'].items():
            value = record[key]
            if kind == 'uuid':
                if str(UUID(value)) != value:
                    raise ValueError('Expected canonical UUID')
            elif kind == 'date-time':
                _date(value)
            elif kind == 'int64':
                if type(value) is not int or not -(2**63) <= value < 2**63:
                    raise ValueError('Expected int64')
            elif kind == 'boolean':
                if type(value) is not bool:
                    raise ValueError('Expected boolean')
            elif not isinstance(value, str):
                raise ValueError('Expected string')
        if record['Id'] in measurement_ids or record['ExperimentId'] not in experiment_ids:
            raise ValueError('Invalid measurement identity or experiment reference')
        measurement_ids.add(record['Id'])
    return model, protocol, hashlib.sha256(raw).hexdigest()


def _wire_query(endpoint, raw_query, protocol):
    pairs = parse_qsl(raw_query, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
    params = {}
    for key, value in pairs:
        if key in params:
            raise ValueError('Repeated query parameter')
        kind = protocol['endpoints'][endpoint]['query'].get(key)
        if kind in ('int32', 'int64'):
            if not re.fullmatch(r'[+-]?[0-9]+', value):
                raise ValueError('Expected integer query parameter')
            value = int(value)
        params[key] = value
    return validate_query(endpoint, params, protocol=protocol)


def _page(records, start, size, count=None):
    if start < 0 or size <= 0 or (count is not None and count < 0):
        raise ValueError('Synthetic pagination requires nonnegative pages and positive size')
    begin = start * size
    return records[begin:] if count is None else records[begin:begin + size * count]


def _experiments(model, params):
    records = copy.deepcopy(model['experiments'])
    if 'NameFilter' in params:
        records = [row for row in records if params['NameFilter'].casefold() in row['Name'].casefold()]
    if 'ApplicationFilter' in params:
        records = [row for row in records if params['ApplicationFilter'].casefold() == row['Application'].casefold()]
    for key, after in (('StartTime', True), ('EndTime', False),
                       ('StartTimeStamp', True), ('EndTimeStamp', False)):
        if key in params:
            bound = _date(params[key]).timestamp() * 1000 if key in ('StartTime', 'EndTime') else params[key]
            records = [row for row in records if
                       (_date(row['CreatedTime']).timestamp() * 1000 >= bound if after else
                        _date(row['CreatedTime']).timestamp() * 1000 <= bound)]
    size = params.get('PageSize', model['synthetic_semantics']['experiment_default_page_size'])
    return _page(records, params.get('PageNumber', 0), size, 1)


class ModelServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer's reverse DNS lookup is unnecessary for an explicitly bound
        # model host and can delay local startup when DNS is unavailable.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def __init__(self, address, model_path, api_key):
        self.model, self.protocol, self.model_sha256 = load_model(model_path)
        if api_key is not None and (not isinstance(api_key, str) or not api_key or
                                    any(not 33 <= ord(character) <= 126 for character in api_key)):
            raise ValueError('Invalid model API key')
        self.api_key = api_key
        if address[1] is None:
            address = (address[0], self.protocol['default_port'])
        super().__init__(address, ModelHandler)


class ModelHandler(BaseHTTPRequestHandler):
    server_version = 'DIYLabBot-Synthetic-UltraC/1'

    def log_message(self, *args):
        # No URLs, query values or Authorization headers in request logs.
        pass

    def _send(self, status, value, **headers):
        raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-DIYLabBot-Synthetic', 'true')
        self.send_header('X-DIYLabBot-Model-SHA256', self.server.model_sha256)
        for key, val in headers.items():
            self.send_header(key, val)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def _authorized(self):
        if self.server.api_key is None:
            return True
        headers = self.headers.get_all('Authorization', [])
        parts = headers[0].split() if len(headers) == 1 else []
        expected = self.server.api_key.encode('ascii')
        if (len(parts) != 2 or parts[0].casefold() != 'bearer' or
                not hmac.compare_digest(parts[1].encode('utf-8'), expected)):
            self._send(401, {'error': 'Bearer authentication required'}, **{'WWW-Authenticate': 'Bearer'})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        try:
            target = urlsplit(self.path)
            endpoint, identifier = None, None
            for name, definition in self.server.protocol['endpoints'].items():
                path = definition['path']
                if '{id}' not in path and target.path == path:
                    endpoint = name
                    break
                if '{id}' in path and target.path.startswith(path.split('{id}')[0]):
                    identifier = str(UUID(target.path[len(path.split('{id}')[0]):]))
                    endpoint = name
                    break
            if endpoint is None:
                unsupported = ('/Measurement/FindPeak', '/StandardReference/', '/UserMethod/')
                status = 501 if any(target.path.startswith(path) for path in unsupported) else 404
                self._send(status, {'error': 'Read endpoint outside this synthetic model' if status == 501 else 'Unknown endpoint'})
                return
            params = _wire_query(endpoint, target.query, self.server.protocol)
            model = self.server.model
            if endpoint == 'system':
                result = model['system']
            elif endpoint == 'query_experiments':
                result = _experiments(model, params)
            elif endpoint in ('experiment', 'experiment_detail'):
                record = next((row for row in model['experiments'] if row['Id'] == identifier), None)
                if record is None:
                    self._send(404, {'error': 'Experiment not found'})
                    return
                result = copy.deepcopy(record)
                if endpoint == 'experiment_detail':
                    result['Measurements'] = [row for row in model['measurements'] if row['ExperimentId'] == identifier]
            else:
                records = [row for row in model['measurements'] if
                           'experimentId' not in params or row['ExperimentId'] == params['experimentId']]
                result = _page(records, params.get('startPage', 0),
                               model['synthetic_semantics']['measurement_page_size'], params.get('pageCount'))
            self._send(200, result)
        except (ValueError, TypeError, OverflowError):
            self._send(400, {'error': 'Invalid path or query parameter'})

    def _reject_write(self):
        if self._authorized():
            self._send(405, {'error': 'This model supports read-only GET requests'}, Allow='GET')
        self.close_connection = True

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _reject_write


def make_server(host='127.0.0.1', port=None, model_path=SOURCE, api_key=None):
    return ModelServer((host, port), model_path, api_key)
