"""DNA-SiLA-2: synthetischer TLS-Server mit expliziten Root-Bestätigungen."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import uuid

import build_dna_quantification_sila2 as contract
from manual_tasks import TaskError


def runtime_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to((contract.ROOT / 'exports').resolve()):
        raise ValueError('DNA runtime files must remain in this worktree exports/ area')
    return path


def private_json(path, value):
    path = runtime_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())


async def serve(args):
    from dna_sila2_server import DNAServer
    users = json.loads(runtime_path(args.credentials).read_text(encoding='utf-8'))
    if set(users) != {'format', 'users'} or users['format'] != 'solidcraftbot.dna-sila-users/1':
        raise ValueError('DNA credential file required')
    application = DNAServer(runtime_path(args.directory), users['users'], runtime_path(args.tls_directory),
        hostname=args.bind, port=args.port, pause_after=args.pause_after)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in [signal.SIGINT, signal.SIGTERM]:
        try:
            loop.add_signal_handler(signum, stopped.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stopped.set))
    started = False
    try:
        await application.start()
        started = True
        ready = {'format': 'solidcraftbot.dna-sila-ready/1', 'server_uuid': application.runtime.server_uuid,
                 'boot_id': application.runtime.boot_id, 'bind': args.bind, 'port': application.port,
                 'tls': True, 'simulation_only': True, 'hardware_available': False,
                 'certificate': str(runtime_path(args.tls_directory) / 'server.crt'),
                 'feature': str(application.feature.fully_qualified_identifier),
                 'journal': str(application.runtime.journal_path)}
        if args.ready_file:
            private_json(args.ready_file, ready)
        print(json.dumps(ready), flush=True)
        await stopped.wait()
    finally:
        if started:
            await application.stop()
        else:
            application.runtime.close()


async def remote(args):
    from cf01_sila2_client import connect_station, wait_for_execution
    if args.out is not None and runtime_path(args.out).exists():
        raise ValueError('Output already exists; choose a new evidence path before dispatch')
    ready = json.loads(runtime_path(args.ready_file).read_text(encoding='utf-8'))
    if ready.get('format') != 'solidcraftbot.dna-sila-ready/1':
        raise ValueError('Explicit DNA SiLA ready file required')
    login = json.loads(runtime_path(args.login_input).read_text(encoding='utf-8'))
    client, auth = await connect_station(ready, login['username'], login['password'], args.timeout)
    lease = None
    uncertain = False
    try:
        feature = client.DnaQuantificationWorkflow
        if args.command in {'status', 'report'}:
            prop = feature.Status if args.command == 'status' else feature.Report
            value = json.loads(await prop.read(metadata=[auth], timeout=args.timeout * 1000))
            result = {'observation': 'authenticated_live_dna_' + args.command, 'tls': True,
                      'server_uuid': ready['server_uuid'], 'process_effects_dispatched': False,
                      'workflow_clock_advanced': False, 'value': value}
        else:
            identifier = str(uuid.uuid4())
            await client.LockController.LockServer(LockIdentifier=identifier, Timeout=args.lease_timeout, metadata=[auth])
            lease = await client.LockController.LockIdentifier.from_native(client, identifier)

            async def call(name, request_id, supplied):
                source = next(c for c in contract.load()['commands'] if c['name'] == name)
                if not isinstance(supplied, dict):
                    raise ValueError('Typed command arguments must be a JSON object')
                arguments = {'request_identifier': request_id, 'run_identifier': args.run_id, **supplied}
                if arguments['request_identifier'] != request_id or arguments['run_identifier'] != args.run_id:
                    raise ValueError('Argument input cannot replace request or root run identity')
                if set(arguments) != {field['name'] for field in source['arguments']}:
                    raise ValueError('Exactly the declared typed DNA command fields are required')
                response = await getattr(feature, name)(metadata=[auth, lease], timeout=args.timeout * 1000,
                    **{contract.camel(key): value for key, value in arguments.items()})
                if hasattr(response, 'get_responses'):
                    response = await wait_for_execution(response, args.timeout)
                return json.loads(response.StatusJson)

            try:
                if args.command == 'scenario':
                    receipts = [await call('CreateRun', str(uuid.uuid4()), {})]
                    scenario = {'initial_dilution': 'none', 'after_range': '', 'nanodrop_concentration': 50.,
                                'qubit_concentration': 500., 'qubit_report_original': False}
                    receipts.append(await call('RunUntilDecision', str(uuid.uuid4()), scenario))
                    first = json.loads(await feature.Report.read(metadata=[auth]))['reports'][args.run_id]
                    attempt = list(first['attempts'].values())[-1]
                    if (first['status'] != 'awaiting_choice'
                            or attempt['evaluations']['qubit']['status'] != 'above_range'
                            or '1+9' not in {option['key'] for option in first['offered_dilutions']}):
                        raise ValueError('The observed root did not offer the planned Qubit-high dilution')
                    receipts.append(await call('ChooseDilution', str(uuid.uuid4()), {
                        'sample_identifier': attempt['sample_id'], 'dilution_preset': '1+9'}))
                    receipts.append(await call('RunUntilDecision', str(uuid.uuid4()), scenario))
                    report = json.loads(await feature.Report.read(metadata=[auth]))['reports'][args.run_id]
                    if report['status'] != 'completed' or report['passed'] is not True:
                        raise ValueError('The observed diluted pair did not complete; inspect the held root')
                    result = {'format': 'solidcraftbot.dna-sila-scenario/1', 'server_uuid': ready['server_uuid'],
                              'boot_id': ready['boot_id'], 'run_id': args.run_id, 'tls': True,
                              'network_executed': True, 'hardware_executed': False, 'ros_executed': False,
                              'scenario': scenario, 'receipts': receipts, 'first_report': first,
                              'report': report, 'journal': ready['journal']}
                else:
                    supplied = {} if args.arguments_input is None else json.loads(runtime_path(args.arguments_input).read_text(encoding='utf-8'))
                    result = await call(args.name, args.request_id, supplied)
            except BaseException:
                uncertain = True  # Never replay or assume terminal effects after a lost receipt.
                raise
        if args.out is not None:
            private_json(args.out, result)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    finally:
        if lease is not None and not uncertain:
            try:
                await client.LockController.UnlockServer(LockIdentifier=identifier, metadata=[auth], timeout=args.timeout * 1000)
            except Exception:
                pass  # Unlocking the transport lease never releases root inventory.
        await client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        epilog='Ausschließlich Simulation: keine Hardware, keine Roboterfahrt und kein ROS-Laufzeitnachweis.')
    commands = parser.add_subparsers(dest='command', required=True)
    initialize = commands.add_parser('init', help='Separate private DNA-Serveridentität und Zugangsdaten anlegen')
    initialize.add_argument('--directory', required=True, type=Path)
    initialize.add_argument('--credentials-input', required=True, type=Path)
    initialize.add_argument('--credentials', required=True, type=Path)
    server = commands.add_parser('serve', help='Synthetischen TLS/gRPC-Server starten')
    server.add_argument('--directory', required=True, type=Path)
    server.add_argument('--credentials', required=True, type=Path)
    server.add_argument('--tls-directory', required=True, type=Path)
    server.add_argument('--ready-file', type=Path)
    server.add_argument('--bind', default='127.0.0.1', choices=['127.0.0.1', 'localhost'])
    server.add_argument('--port', type=int, default=0)
    server.add_argument('--pause-after', choices=['dilution_intent', 'measurement_intent'],
        help='Private Testinjektion am Server; kein Netzwerkparameter und keine automatische Bestätigung')
    for name in ['status', 'report', 'command', 'scenario']:
        child = commands.add_parser(name)
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
            child.add_argument('--arguments-input', type=Path, help='Exakt die weiteren typisierten Argumente des generierten Vertrags')
    args = parser.parse_args(argv)
    try:
        if getattr(args, 'timeout', 1) <= 0:
            raise ValueError('Positive network timeout required')
        if args.command == 'init':
            from cf01_sila2_auth import credential
            from dna_sila2_runtime import DNARuntime
            supplied = json.loads(runtime_path(args.credentials_input).read_text(encoding='utf-8'))
            if not isinstance(supplied, list) or not supplied or len({u['username'] for u in supplied}) != len(supplied):
                raise ValueError('Nonempty unique DNA users required')
            users = [credential(u['username'], u['password'], u['role']) for u in supplied]
            private_json(args.credentials, {'format': 'solidcraftbot.dna-sila-users/1', 'users': users})
            runtime = DNARuntime(runtime_path(args.directory))
            try:
                print(json.dumps({'initialized': True, 'server_uuid': runtime.server_uuid,
                                  'simulation_only': True, 'hardware_available': False}))
            finally:
                runtime.close()
        elif args.command == 'serve':
            asyncio.run(serve(args), debug=False)
        else:
            asyncio.run(remote(args), debug=False)
    except (TaskError, ValueError, OSError, RuntimeError) as error:
        parser.exit(1, 'Abbruch: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
