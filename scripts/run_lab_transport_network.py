"""Local HTTPS courier interface over the synthetic T2 workflow; no hardware."""
import argparse
from collections import defaultdict
import copy
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import uuid

import async_transport_domain as domain
from lab_transport_access import credential
from lab_transport_http import TransportClient, TransportHTTPServer, tls_identity
from lab_transport_network import NetworkWorkflow, Service
from lab_transport_network_sources import SOURCE
from manual_tasks import Journal, TaskError
from manual_workflow_cli import output_path
from run_lab_workflow import ACTOR, run_nanodrop, run_qubit

ROOT = Path(__file__).resolve().parents[1]


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        stream.flush(); os.fsync(stream.fileno())


def initialize(directory, *, store=None, run_id='SYN.LAB.T3', source=SOURCE, prepare_demo=False):
    """Initialize once; only the explicit demo flag invents positive CF01 inputs.

    A generated password handoff is private local bootstrap data. Passwords and
    tokens are never emitted to stdout, written to the journal, or committed.
    """
    directory = output_path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise TaskError('Use a new private service directory; existing evidence is preserved')
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    store = output_path(store or directory / 'workflows.sqlite3')
    with Journal(store) as journal:
        flow = NetworkWorkflow.create(journal, source, run_id)
        try:
            if prepare_demo:
                flow.accept_rack(ACTOR, observations=flow.inventory_observations())
                for sample in flow.state['definition']['manifest']['samples']:
                    flow.confirm_mass(ACTOR, sample['vessel_id'], mass_g=2.0, content_revision=0)
                flow.run_cf01(ACTOR)
            state = flow.state
            topology = state['definition']['transport']['topology']
            server_uuid = state['network']['server_uuid']
        finally:
            flow.close()
    definitions = [('owner', topology['owner_principal'],
                    [{'id': 'Owner', 'kind': 'owner', 'resource_id': run_id}])]
    by_endpoint = defaultdict(list)
    for index, item in enumerate(topology['endpoints'], 1):
        by_endpoint[item['principal']].append({'id': 'Endpoint%02d' % index,
                                              'kind': 'endpoint', 'resource_id': item['id']})
    definitions += [('endpoint-%d' % index, principal, grants)
                    for index, (principal, grants) in enumerate(by_endpoint.items(), 1)]
    definitions += [('agent-%d' % index, item['principal'],
                     [{'id': 'Agent%02d' % index, 'kind': 'agent', 'resource_id': item['id']}])
                    for index, item in enumerate(topology['agents'], 1)]
    definitions.append(('observer', 'SYN.Transport.Observer',
                        [{'id': 'Observer', 'kind': 'observer', 'resource_id': run_id}]))
    users, bootstrap = [], []
    for username, principal, grants in definitions:
        password = secrets.token_urlsafe(24)
        users.append(credential(username, password, principal, grants))
        bootstrap.append({'username': username, 'password': password,
                          'principal': principal, 'grants': grants})
    private_json(directory / 'users.json', {'format': 'solidcraftbot.lab-transport-users/1', 'users': users})
    private_json(directory / 'bootstrap.json', {'format': 'solidcraftbot.lab-transport-bootstrap/1',
                                               'server_uuid': server_uuid, 'accounts': bootstrap})
    private_json(directory / 'service.json', {'format': 'solidcraftbot.lab-transport-service/1',
                                             'store': str(store), 'run_id': run_id, 'server_uuid': server_uuid})
    certificate, _ = tls_identity(directory / 'tls', server_uuid)
    return {'directory': str(directory), 'store': str(store), 'run_id': run_id,
            'server_uuid': server_uuid, 'certificate': str(certificate),
            'bootstrap_file': str(directory / 'bootstrap.json'),
            'synthetic_cf01_boundary_prepared': bool(prepare_demo),
            'network_executed': False, 'hardware_executed': False}


def run_demo(directory, *, store=None, run_id='SYN.LAB.T3.Demo', source=SOURCE):
    """Explicit TLS test driver; never a browser's automatic confirmation loop."""
    setup = initialize(directory, store=store, run_id=run_id, source=source, prepare_demo=True)
    directory = Path(setup['directory'])
    accounts = domain._json((directory / 'bootstrap.json').read_bytes())['accounts']
    service = Service(directory, source=source)
    server = None
    thread = None
    try:
        server = TransportHTTPServer(service, directory / 'tls')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        clients = {}
        for account in accounts:
            client = TransportClient(server.origin, server.certificate_path)
            client.login(account['username'], account['password'], setup['server_uuid'])
            clients[account['username']] = client
        owner = clients['owner']
        owner_grant = next(grant['id'] for account in accounts if account['username'] == 'owner'
                           for grant in account['grants'] if grant['kind'] == 'owner')
        serial = 0

        def request(client, grant_id, operation, args):
            nonlocal serial
            serial += 1
            return client.submit('Demo.Request.%03d' % serial, grant_id, operation, args)

        def owner_args(extra=None):
            snapshot = owner.snapshot()
            return {**(extra or {}), 'boot_id': snapshot['boot_id'],
                    'assignment_epoch': snapshot['assignment_epoch']}

        request(owner, owner_grant, 'resume', owner_args())
        reconciliation = owner.snapshot()['workflow_reconcile']
        if not reconciliation['allowed']:
            raise TaskError('The new demo boundary requires an explicit supported workflow reconciliation')
        request(owner, reconciliation['grant_id'], 'reconcile', {
            **reconciliation['args_template'], 'workspace_clear': True, 'arm_clear': True,
            'gripper_empty': True, 'manifest_confirmed': True})

        def start_route(route_id, job_id):
            request(owner, owner_grant, 'prepare_route', owner_args({'route_id': route_id, 'job_id': job_id}))
            result = request(owner, owner_grant, 'dispatch', owner_args({'job_id': job_id}))
            job = next(item for item in result['snapshot']['jobs'] if item['job_id'] == job_id)
            if job['receipts']:
                raise TaskError('Owner dispatch must not fabricate handover attestations')

        def deliver(job_id):
            # Four separate authenticated fixture contexts, never a worker
            # batch that invents endpoint observations under one credential.
            for role in ('delivery_accept', 'delivery_release', 'pickup_accept', 'pickup_release'):
                found = None
                for account in accounts:
                    client = clients[account['username']]
                    snapshot = client.snapshot()
                    for job in snapshot['jobs']:
                        if job['job_id'] != job_id: continue
                        action = next((action for action in job['allowed_actions']
                                       if action['operation'] == 'attest' and action['role'] == role), None)
                        if action:
                            found = client, action, job
                            break
                    if found: break
                if found is None: raise TaskError('No authorized demo actor for ' + role)
                client, action, job = found
                request(client, action['grant_id'], 'attest', {
                    'job_id': job_id, 'role': role, 'observation_id': 'Demo.' + job_id + '.' + role,
                    'assignment_epoch': job['assignment_epoch'],
                    'handover_id': job['pickup_handover_id'] if role.startswith('pickup') else job['delivery_handover_id'],
                    'manifest_sha256': job['manifest_sha256'], 'observed_rack_id': job['rack_id'], 'confirmed': True})

        start_route('CF01ToNanoDrop', 'Network.ToNanoDrop')
        deliver('Network.ToNanoDrop')
        with Journal(Path(setup['store'])) as journal:
            # This local test scheduler belongs to the same service process.
            # The opaque owner session is never included in a network DTO.
            state, _ = journal.get_current(run_id)
            flow = NetworkWorkflow(journal, run_id, session=state['session'])
            run_nanodrop(flow, before_import=lambda current: start_route('NanoDropToQubit', 'Network.ToQubit'))
            deliver('Network.ToQubit')
            run_qubit(flow)
            report = flow.report()
            if not report['passed'] or not report['transport_network_executed']:
                raise TaskError('TLS demo did not complete the authenticated workflow')
            private_json(directory / 'demo-report.json', report)
        return {'passed': True, 'run_id': run_id, 'transport_network_executed': True,
                'instrument_network_executed': False, 'hardware_executed': False,
                'robot_motion_executed': False, 'report': str(directory / 'demo-report.json'),
                'bookings': len(report['bookings']), 'samples': len(report['samples']),
                'known_remaining_volume_ul': report['samples']['Sample01']['remaining_volume_ul'],
                'unknown_volume_preserved': report['samples']['Sample03']['remaining_volume_ul'] is None}
    finally:
        if server is not None:
            if thread is not None: server.shutdown(); thread.join(timeout=5)
            server.server_close()
        service.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'exports/transport-courier')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'demo'):
        child = sub.add_parser(name)
        child.add_argument('--store', type=Path)
        child.add_argument('--run-id', default='SYN.LAB.T3' if name == 'init' else 'SYN.LAB.T3.Demo')
        child.add_argument('--profile', type=Path, default=SOURCE)
        if name == 'init': child.add_argument('--prepare-demo', action='store_true')
    child = sub.add_parser('serve')
    child.add_argument('--host', choices=('127.0.0.1', 'localhost'), default='127.0.0.1')
    child.add_argument('--port', type=int, default=0)
    child = sub.add_parser('report')
    child.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            result = initialize(args.directory, store=args.store, run_id=args.run_id,
                                source=args.profile, prepare_demo=args.prepare_demo)
        elif args.command == 'demo':
            result = run_demo(args.directory, store=args.store, run_id=args.run_id, source=args.profile)
        else:
            service = Service(args.directory)
            try:
                if args.command == 'serve':
                    server = TransportHTTPServer(service, service.directory / 'tls', args.host, args.port)
                    try:
                        print(json.dumps({**service.info(), 'url': server.origin,
                                          'certificate': str(server.certificate_path),
                                          'bootstrap_file': str(service.directory / 'bootstrap.json')}), flush=True)
                        server.serve_forever()
                    except KeyboardInterrupt:
                        pass
                    finally:
                        server.server_close()
                    return 0
                with Journal(service.store) as journal:
                    result = NetworkWorkflow(journal, service.run_id).report()
                if args.out:
                    destination = output_path(args.out)
                    private_json(destination, result)
                    result = {'report': str(destination), 'passed': result['passed']}
            finally:
                service.close()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (TaskError, PermissionError, ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': type(error).__name__, 'message': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
