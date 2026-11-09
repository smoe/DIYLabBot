"""Serve the synthetic UltraC model or archive one documented read-only request."""
import argparse
import json
import os
import sys
from pathlib import Path

from nanodrop_ultra_model import SOURCE as MODEL_SOURCE, make_server
from nanodrop_ultra_network import NanoDropNetworkError, NanoDropUltraClient, validate_query

ROOT = Path(__file__).resolve().parents[1]


def _key(name):
    if name is None:
        return None
    value = os.environ.get(name)
    if not value:
        raise ValueError('The selected API-key environment variable is empty or missing')
    return value


def _output(path):
    path = path.resolve()
    if not path.is_relative_to((ROOT / 'exports').resolve()):
        raise ValueError('Runtime archives must stay inside this project exports/ directory')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve', help='Synthetic fixture server; loopback by default')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, help='Default from the referenced protocol; 0 selects a free port')
    serve.add_argument('--model', type=Path, default=MODEL_SOURCE)
    serve.add_argument('--api-key-env', help='Environment variable containing the optional model token')
    read = sub.add_parser('read', help='One GET against a model or an explicitly configured device')
    read.add_argument('--base-url', required=True)
    read.add_argument('--api-key-env', help='Environment variable containing the SciVault token')
    read.add_argument('--endpoint', required=True, choices=(
        'system', 'query_experiments', 'experiment', 'experiment_detail', 'measurements'))
    read.add_argument('--id', help='Experiment UUID for the two Id routes')
    read.add_argument('--query', default='{}', help='JSON object with exact manufacturer query names')
    read.add_argument('--timeout', type=float, default=5)
    read.add_argument('--max-response-bytes', type=int, default=8 * 1024 * 1024)
    read.add_argument('--out', type=Path, required=True, help='New archive directory under exports/')
    args = parser.parse_args(argv)
    try:
        key = _key(args.api_key_env)
        if args.command == 'serve':
            with make_server(args.host, args.port, args.model, key) as server:
                print(json.dumps({'base_url': f'http://{args.host}:{server.server_port}/',
                                  'synthetic': True, 'model_sha256': server.model_sha256,
                                  'hardware_verified': False}), flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
            return 0
        output = _output(args.out)
        if output.exists():
            raise ValueError('Archive directory already exists; choose a new path')
        params = json.loads(args.query)
        params = validate_query(args.endpoint, params)
        uses_id = args.endpoint in ('experiment', 'experiment_detail')
        if uses_id != (args.id is not None):
            raise ValueError('Only experiment and experiment_detail require --id')
        client = NanoDropUltraClient(args.base_url, api_key=key, timeout=args.timeout,
                                    max_response_bytes=args.max_response_bytes)
        failed = False
        try:
            if uses_id:
                response = getattr(client, args.endpoint)(args.id)
            elif args.endpoint == 'measurements':
                response = client.measurements(experiment_id=params.get('experimentId'),
                                               start_page=params.get('startPage'),
                                               page_count=params.get('pageCount'))
            elif args.endpoint == 'query_experiments':
                response = client.query_experiments(**params)
            else:
                response = client.system()
        except NanoDropNetworkError as error:
            response = getattr(error, 'response', None)
            if response is None:
                raise
            failed = True
        client.archive(response, output)
        print(json.dumps({'archive': str(output), 'status': response.status,
                          'request_succeeded': not failed,
                          'body_complete': response.body_complete,
                          'workflow_imported': False, 'inventory_changed': False,
                          'hardware_verified': False}, ensure_ascii=False))
        return 1 if failed else 0
    except (NanoDropNetworkError, ValueError, OSError, KeyError, TypeError) as error:
        # Neither credentials nor remote error bodies belong in terminal output.
        print(json.dumps({'error': type(error).__name__,
                          'message': 'Request/model configuration failed; no workflow effect'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
