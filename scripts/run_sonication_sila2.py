"""S09 SiLA 2: synthetic loopback TLS over the existing CUT&RUN root."""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import signal
import sys
import uuid

import build_cutrun_input_sonication_sila2 as contract
from manual_tasks import TaskError

USERS_FORMAT = 'solidcraftbot.sonication-sila-users/1'
READY_FORMAT = 'solidcraftbot.sonication-sila-ready/1'
SCENARIO_FORMAT = 'solidcraftbot.sonication-sila-scenario/1'


def runtime_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to((contract.ROOT / 'exports').resolve()):
        raise ValueError('S09 runtime files must remain in this worktree exports/ area')
    return path


def check_output_parents(path):
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError('Output parent must be a directory: ' + str(parent))


def new_output(value):
    """Reject blocked ancestors before connecting or creating root state."""
    path = runtime_path(value)
    if path.exists():
        raise ValueError('Output already exists; choose a new evidence path before dispatch')
    check_output_parents(path)
    return path


def directory_path(value):
    path = runtime_path(value)
    if path.exists() and not path.is_dir():
        raise ValueError('Runtime directory must be a directory: ' + str(path))
    check_output_parents(path)
    return path


def private_json(path, value):
    path = new_output(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def read_login(path):
    login = json.loads(runtime_path(path).read_text(encoding='utf-8'))
    if (not isinstance(login, dict) or set(login) != {'username', 'password'}
            or not all(isinstance(value, str) and value for value in login.values())):
        raise ValueError('Private username/password JSON required')
    return login


async def serve(args):
    # All requested output paths are checked before a runtime or TLS identity is opened.
    directory = directory_path(args.directory)
    certificate_directory = directory_path(args.tls_directory)
    if args.ready_file is not None:
        new_output(args.ready_file)
    users = json.loads(runtime_path(args.credentials).read_text(encoding='utf-8'))
    if (not isinstance(users, dict) or set(users) != {'format', 'users'}
            or users['format'] != USERS_FORMAT):
        raise ValueError('S09 credential file required')
    from sonication_sila2_server import SonicationServer
    application = SonicationServer(directory, users['users'], certificate_directory,
        hostname=args.bind, port=args.port, pause_after=args.pause_after)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stopped.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stopped.set))
    started = False
    try:
        await application.start()
        started = True
        ready = {'format': READY_FORMAT, 'server_uuid': application.runtime.server_uuid,
                 'boot_id': application.runtime.boot_id, 'bind': args.bind, 'port': application.port,
                 'tls': True, 'simulation_only': True, 'hardware_available': False,
                 'certificate': str(certificate_directory / 'server.crt'),
                 'feature': str(application.feature.fully_qualified_identifier),
                 'journal': str(application.runtime.journal_path)}
        if args.ready_file is not None:
            private_json(args.ready_file, ready)
        print(json.dumps(ready), flush=True)
        await stopped.wait()
    finally:
        if started:
            await application.stop()
        else:
            application.runtime.close()


async def remote(args):
    # A known invalid output must never dispatch a command, even if the endpoint is live.
    if args.out is not None:
        new_output(args.out)
    ready = json.loads(runtime_path(args.ready_file).read_text(encoding='utf-8'))
    if not isinstance(ready, dict) or ready.get('format') != READY_FORMAT:
        raise ValueError('Explicit S09 SiLA ready file required')
    login = read_login(args.login_input)
    from cf01_sila2_client import connect_station, wait_for_execution
    try:
        client, auth = await connect_station(ready, login['username'], login['password'], args.timeout)
    except Exception as error:
        raise RuntimeError('Could not connect to the authenticated S09 TLS endpoint: ' + str(error)) from None
    lease = None
    uncertain = False
    try:
        feature = client.CutRunInputSonicationWorkflow
        if args.command in {'status', 'report'}:
            prop = feature.Status if args.command == 'status' else feature.Report
            value = json.loads(await prop.read(metadata=[auth], timeout=args.timeout * 1000))
            result = {'observation': 'authenticated_live_s09_' + args.command, 'tls': True,
                      'server_uuid': ready['server_uuid'], 'process_effects_dispatched': False,
                      'workflow_clock_advanced': False, 'value': value}
        else:
            identifier = str(uuid.uuid4())
            await client.LockController.LockServer(LockIdentifier=identifier, Timeout=args.lease_timeout,
                metadata=[auth], timeout=args.timeout * 1000)
            lease = await client.LockController.LockIdentifier.from_native(client, identifier)

            async def call(name, request_id, supplied):
                source = next(c for c in contract.load()['commands'] if c['name'] == name)
                if not isinstance(supplied, dict):
                    raise ValueError('Typed command arguments must be a JSON object')
                arguments = {'request_identifier': request_id, 'run_identifier': args.run_id, **supplied}
                if arguments['request_identifier'] != request_id or arguments['run_identifier'] != args.run_id:
                    raise ValueError('Argument input cannot replace request or root run identity')
                if set(arguments) != {field['name'] for field in source['arguments']}:
                    raise ValueError('Exactly the declared typed S09 command fields are required')
                response = await getattr(feature, name)(metadata=[auth, lease], timeout=args.timeout * 1000,
                    **{contract.camel(key): value for key, value in arguments.items()})
                if hasattr(response, 'get_responses'):
                    response = await wait_for_execution(response, args.timeout)
                return json.loads(response.StatusJson)

            try:
                if args.command == 'scenario':
                    scenario = {'scenario_identifier': 'normal'}
                    receipts = [await call('CreateRun', str(uuid.uuid4()), scenario),
                                await call('RunUntilDecision', str(uuid.uuid4()), {})]
                    report = json.loads(await feature.Report.read(metadata=[auth], timeout=args.timeout * 1000))['reports'][args.run_id]
                    fixture = json.loads((contract.ROOT / contract.load()['fixture']['source']).read_bytes())
                    intents = report['sonication']['intents']
                    if len(intents) != 1:
                        raise ValueError('The observed root lacks its one canonical S09 sonication')
                    intent = next(iter(intents.values()))
                    expected = fixture['input_lysate_ul'] - fixture['qc_withdrawal_ul']
                    if (report['sop']['stages'][intent['stage_run_id']]['status'] != 'completed'
                            or report['status'] in {'completed', 'cancelled'} or not report['resources']
                            or report['remaining'][intent['material_after_id']]['value'] != expected
                            or report['inventory']['vessels'][intent['vessel_id']]['location'] != intent['original_rack_location']):
                        raise ValueError('The observed S09 fixture did not complete with its held root and canonical balance')
                    result = {'format': SCENARIO_FORMAT, 'server_uuid': ready['server_uuid'],
                              'boot_id': ready['boot_id'], 'run_id': args.run_id, 'tls': True,
                              'network_executed': True, 'hardware_executed': False, 'ros_executed': False,
                              'scenario': scenario, 'receipts': receipts, 'report': report,
                              'journal': ready['journal']}
                else:
                    supplied = {} if args.arguments_input is None else json.loads(
                        runtime_path(args.arguments_input).read_text(encoding='utf-8'))
                    result = await call(args.name, args.request_id, supplied)
            except BaseException:
                uncertain = True  # Keep the request identity; never replay a lost receipt.
                raise
        if args.out is not None:
            private_json(args.out, result)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception as error:
        raise RuntimeError('S09 remote operation failed; retain the request identity and inspect the root: '
                           + str(error)) from None
    finally:
        if lease is not None and not uncertain:
            try:
                await client.LockController.UnlockServer(LockIdentifier=identifier, metadata=[auth],
                    timeout=args.timeout * 1000)
            except Exception:
                pass  # Transport unlock never releases CUT&RUN root reservations.
        await client.close()


def main(argv=None):
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument('--language', choices=['de', 'en'], default='de')
    language = preliminary.parse_known_args(argv)[0].language
    de = language == 'de'
    parser = argparse.ArgumentParser(parents=[preliminary], description=(
        'S09 SiLA 2: synthetischer TLS-Server am bestehenden CUT&RUN-Root.' if de else
        'S09 SiLA 2: synthetic TLS server over the existing CUT&RUN root.'),
        epilog=('Nur Software-Fixtures: keine Geräte-, Ultraschall-, Bewegungs- oder ROS-Ausführung.' if de else
                'Software fixtures only: no device, ultrasound, motion or ROS execution.'))
    commands = parser.add_subparsers(dest='command', required=True)
    initialize = commands.add_parser('init', help='Private S09-Identität und Zugangsdaten anlegen' if de else
                                    'Initialize private S09 identity and credentials')
    initialize.add_argument('--directory', required=True, type=Path)
    initialize.add_argument('--credentials-input', required=True, type=Path,
                           help='Private JSON-Datei mit username/password/role' if de else
                                'Private JSON file with username/password/role')
    initialize.add_argument('--credentials', required=True, type=Path)
    server = commands.add_parser('serve', help='Synthetischen TLS/gRPC-Server starten' if de else
                                'Start synthetic TLS/gRPC server')
    server.add_argument('--directory', required=True, type=Path)
    server.add_argument('--credentials', required=True, type=Path)
    server.add_argument('--tls-directory', required=True, type=Path)
    server.add_argument('--ready-file', type=Path)
    server.add_argument('--bind', default='127.0.0.1', choices=['127.0.0.1', 'localhost'])
    server.add_argument('--port', type=int, default=0)
    server.add_argument('--pause-after', choices=['input_preparation_intent', 'sonication_intent',
        'sonication_confirmed', 'qc_withdrawal_intent', 'opening_complete', 'phase_time', 'qc_confirmed'],
        help=('Private Server-Testinjektion; kein Netzwerkparameter' if de else
              'Private server test injection; never a network parameter'))
    helps = {'status': ('Live-Status lesen', 'Read live status'),
             'report': ('Root-Bericht lesen', 'Read root report'),
             'command': ('Typisierten S09-Befehl ausführen', 'Execute a typed S09 command'),
             'scenario': ('Gepinnte normale Software-Fixture ausführen', 'Run the pinned normal software fixture')}
    for name in ('status', 'report', 'command', 'scenario'):
        child = commands.add_parser(name, help=helps[name][0 if de else 1])
        child.add_argument('--ready-file', required=True, type=Path)
        child.add_argument('--login-input', required=True, type=Path)
        child.add_argument('--out', type=Path, required=name == 'scenario')
        child.add_argument('--timeout', type=float, default=10)
        if name in {'command', 'scenario'}:
            child.add_argument('--run-id', required=True)
            child.add_argument('--lease-timeout', type=int, default=30)
        if name == 'command':
            child.add_argument('--name', choices=sorted(contract.COMMANDS), required=True)
            child.add_argument('--request-id', required=True)
            child.add_argument('--arguments-input', type=Path,
                help='Weitere typisierte Argumente als JSON' if de else 'Further typed arguments as JSON')
    args = parser.parse_args(argv)
    try:
        timeout = getattr(args, 'timeout', 1)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Finite positive network timeout required')
        if getattr(args, 'lease_timeout', 1) <= 0:
            raise ValueError('Positive write-lease timeout required')
        if args.command == 'init':
            output = new_output(args.credentials)
            directory = directory_path(args.directory)
            supplied = json.loads(runtime_path(args.credentials_input).read_text(encoding='utf-8'))
            if (not isinstance(supplied, list) or not supplied
                    or any(not isinstance(u, dict) or set(u) != {'username', 'password', 'role'} for u in supplied)
                    or len({u['username'] for u in supplied}) != len(supplied)):
                raise ValueError('Nonempty unique S09 users required')
            from cf01_sila2_auth import credential
            from sonication_sila2_runtime import SonicationRuntime
            users = [credential(u['username'], u['password'], u['role']) for u in supplied]
            runtime = SonicationRuntime(directory)
            try:
                private_json(output, {'format': USERS_FORMAT, 'users': users})
                print(json.dumps({'initialized': True, 'server_uuid': runtime.server_uuid,
                                  'simulation_only': True, 'hardware_available': False}))
            finally:
                runtime.close()
        elif args.command == 'serve':
            asyncio.run(serve(args), debug=False)
        else:
            asyncio.run(remote(args), debug=False)
    except (TaskError, ValueError, OSError, RuntimeError, ImportError) as error:
        parser.exit(1, ('Abbruch: ' if de else 'Stopped: ') + str(error) + '\n')


if __name__ == '__main__':
    main()
