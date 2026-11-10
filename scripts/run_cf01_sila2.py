"""CF01 SiLA 2 server CLI. Simulation only; all runtime files stay in the project."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys

import build_cf01_sila2 as contract
from cf01_sila2_auth import credential
from cf01_sila2_runtime import StationRuntime, reconcile_station, source_signature
from cf01_sila2_store import ProcessStore


def project_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(contract.ROOT.resolve()):
        raise ValueError('Runtime files must remain inside this project/worktree')
    return path


def runtime_path(value):
    path = project_path(value)
    if not path.is_relative_to((contract.ROOT / 'exports').resolve()):
        raise ValueError('Station runtime data must remain in the ignored exports/ area')
    return path


def private_json(path, data):
    path = runtime_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=2)
        file.write('\n')
        file.flush()
        os.fsync(file.fileno())


async def serve(args):
    from cf01_sila2_server import CF01Server
    users = json.loads(project_path(args.credentials).read_text())
    if users['format'] != 'solidcraftbot.cf01-sila-users/1':
        raise ValueError('Unsupported credential format')
    application = CF01Server(runtime_path(args.store), users['users'], runtime_path(args.tls_directory),
                             hostname=args.bind, port=args.port)
    terminated = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, terminated.set)
        except NotImplementedError:  # Windows event loop
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(terminated.set))
    started = False
    try:
        await application.start(discovery=args.discovery)
        started = True
        ready = {'server_uuid': application.runtime.store.server_uuid, 'boot_id': application.runtime.sim.boot_id,
                 'bind': args.bind, 'port': application.port, 'tls': True,
                 'certificate': str(runtime_path(args.tls_directory) / 'server.crt'),
                 'simulation_only': True, 'hardware_available': False,
                 'clock_mode': application.runtime.clock_mode}
        if args.ready_file:
            private_json(args.ready_file, ready)
        print(json.dumps(ready), flush=True)
        await terminated.wait()
    finally:
        if started:
            await application.stop()
        else:
            application.runtime.close()


def run_batch(args):
    from cf01_rack_batch import Runner, BatchError
    from cf01_sila2_batch import ClientJournal, NetworkStation
    output = runtime_path(args.out)
    if output.exists():
        raise ValueError('Batch report already exists; choose a new output path')
    ready = json.loads(runtime_path(args.ready_file).read_text())
    login = json.loads(runtime_path(args.login_input).read_text())
    journal = ClientJournal(runtime_path(args.journal))
    station = None
    try:
        station = NetworkStation(ready, login['username'], login['password'], journal)
        runner = Runner(transport='sila2', station_backend=station, checkpoint=journal.checkpoint)
        try:
            report = runner.run()
        except BatchError as error:
            report = error.report
        private_json(output, report)
        print(json.dumps({key: report[key] for key in
                         ('passed', 'mode', 'order_restored', 'spin_completed', 'network_executed', 'hardware_executed')}))
        return report['passed']
    finally:
        if station is not None:
            station.close()
        journal.close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument('--language', choices=['de', 'en'], default='de')
    language = preliminary.parse_known_args(argv)[0].language
    description = ('CF01-SiLA-2-Server: ausschließlich Simulation mit TLS und explizitem Wiederanlaufabgleich.'
                   if language == 'de' else 'CF01 SiLA 2 server: simulation only, TLS and explicit recovery reconciliation.')
    parser = argparse.ArgumentParser(description=description, parents=[preliminary])
    sub = parser.add_subparsers(dest='command', required=True)
    initialize = sub.add_parser('init', help='Zugangsdaten initialisieren' if language == 'de' else 'Initialize credentials')
    initialize.add_argument('--credentials-input', required=True, type=Path,
                            help='Private JSON-Datei mit username/password/role' if language == 'de' else 'Private JSON file with username/password/role')
    initialize.add_argument('--credentials', required=True, type=Path)
    initialize.add_argument('--store', required=True, type=Path)
    server = sub.add_parser('serve', help='TLS-Server starten' if language == 'de' else 'Start TLS server')
    server.add_argument('--store', required=True, type=Path)
    server.add_argument('--credentials', required=True, type=Path)
    server.add_argument('--tls-directory', required=True, type=Path)
    server.add_argument('--bind', default='127.0.0.1')
    server.add_argument('--port', type=int, default=0)
    server.add_argument('--ready-file', type=Path)
    server.add_argument('--discovery', action='store_true')
    inspect = sub.add_parser('inspect', help='Gespeicherten Prüfpunkt lesen' if language == 'de' else 'Read stored checkpoint')
    inspect.add_argument('--store', required=True, type=Path)
    status = sub.add_parser('status', help='Station lesend erneut verbinden' if language == 'de' else 'Reconnect for live station status')
    status.add_argument('--ready-file', required=True, type=Path)
    status.add_argument('--login-input', required=True, type=Path)
    status.add_argument('--out', required=True, type=Path)
    reconcile = sub.add_parser('reconcile', help='Synthetischen Wiederanlaufabgleich bestätigen' if language == 'de' else 'Confirm synthetic restart reconciliation')
    reconcile.add_argument('--store', required=True, type=Path)
    reconcile.add_argument('--observation', required=True, type=Path)
    batch = sub.add_parser('batch', help='Chargenlauf über TLS ausführen' if language == 'de' else 'Run the batch over TLS')
    batch.add_argument('--ready-file', required=True, type=Path)
    batch.add_argument('--login-input', required=True, type=Path,
                       help='Private JSON-Datei mit username/password' if language == 'de' else 'Private JSON file with username/password')
    batch.add_argument('--journal', required=True, type=Path)
    batch.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            users = json.loads(project_path(args.credentials_input).read_text())
            if not isinstance(users, list) or not users:
                raise ValueError('Input must contain a nonempty list of users')
            if len({u['username'] for u in users}) != len(users):
                raise ValueError('Duplicate usernames')
            hashed = [credential(u['username'], u['password'], u['role']) for u in users]
            private_json(args.credentials, {'format': 'solidcraftbot.cf01-sila-users/1', 'users': hashed})
            runtime = StationRuntime(runtime_path(args.store))
            print(json.dumps({'initialized': True, 'server_uuid': runtime.store.server_uuid,
                              'simulation_only': True, 'credentials': str(project_path(args.credentials))}))
            runtime.close()
        elif args.command == 'serve':
            asyncio.run(serve(args), debug=False)
        elif args.command == 'batch':
            if not run_batch(args):
                raise SystemExit(1)
        elif args.command == 'status':
            from cf01_sila2_client import read_station_status
            ready = json.loads(runtime_path(args.ready_file).read_text())
            login = json.loads(runtime_path(args.login_input).read_text())
            observed = asyncio.run(read_station_status(ready, login['username'], login['password']))
            private_json(args.out, observed)
            print(json.dumps({'observation': observed['observation'], 'boot_changed': observed['boot_changed'],
                              'process_effects_dispatched': False, 'snapshot': str(runtime_path(args.out))}))
        elif args.command == 'inspect':
            path = runtime_path(args.store)
            if not path.is_file():
                raise ValueError('Station store does not exist')
            with ProcessStore(path, source_signature()) as store:
                snapshot = store.read_snapshot()
                print(json.dumps({'server_uuid': store.server_uuid, 'observation': 'stored_checkpoint_not_live_state',
                                  'pending': store.pending(),
                                  'boot_id': snapshot['backend']['boot_id'] if snapshot else None,
                                  'needs_reconciliation': bool(snapshot and (snapshot['needs_reconciliation'] or snapshot['backend']['owner'])) or bool(store.pending()),
                                  'last_recorded_fault': snapshot['backend']['fault'] if snapshot else None,
                                  'last_recorded_rotor_slots': snapshot['backend']['slots'] if snapshot else None}))
        else:
            reconcile_station(runtime_path(args.store), json.loads(project_path(args.observation).read_text()))
            print(json.dumps({'reconciled': True, 'evidence': 'synthetic_person_confirmation', 'hardware_executed': False}))
    except (ValueError, OSError, RuntimeError) as error:
        prefix = 'Abbruch' if language == 'de' else 'Stopped'
        parser.exit(1, prefix + ': ' + str(error) + '\n')


if __name__ == '__main__':
    main()
