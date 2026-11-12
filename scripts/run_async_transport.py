"""Run T0/T1 synthetic A/B transports: teleportation mocks, no physical motion."""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from manual_tasks import Journal, TaskError, encoded
from manual_workflow import resolve_store
from manual_workflow_cli import output_path
from async_transport import AsyncTransport
import async_transport_domain as domain
from async_transport_adapters import HumanTeleportMock, RobotTeleportMock


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TaskError('Duplicate input field: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise TaskError('Nonfinite input: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def run_demo(flow):
    """Explicit fixture observations; three jobs and no material effects."""
    definition = flow.state['definition']
    principal = definition['owner_principal']
    flow.act('admit', principal, 'demo.admit')
    before = copy.deepcopy(flow.state['inventory'])
    endpoints = definition['endpoints']
    racks = definition['racks']
    humans = [a for a in definition['agents'] if a['kind'] == 'human']
    robots = [a for a in definition['agents'] if a['kind'] == 'robot']
    if len(racks) != 2 or not humans or not robots:
        raise TaskError('A/B demo requires two racks and human/robot fixture agents')
    first_lab = next(p['lab_id'] for p in endpoints if p['id'] == racks[0]['initial_endpoint'])
    targets = [p['id'] for p in endpoints if p['lab_id'] != first_lab]
    if len(targets) < 2:
        raise TaskError('A/B demo requires two destination places in the other lab')
    human = HumanTeleportMock(humans[0]['id'])
    robot = RobotTeleportMock(robots[0]['id'],
        order=('delivery_accept', 'delivery_release', 'pickup_accept', 'pickup_release'))
    stages = [('OutHuman', racks[0]['id'], targets[0], humans[0]['id'], human),
              ('OutRobot', racks[1]['id'], targets[1], robots[0]['id'], robot)]
    batches = []
    for job, rack, target, agent, adapter in stages:
        for operation, arguments in [
            ('request', {'job_id': job, 'rack_id': rack, 'target_endpoint': target, 'agent_id': agent}),
            ('reserve', {'job_id': job}), ('prepare', {'job_id': job})]:
            flow.act(operation, principal, 'demo.' + job + '.' + operation, **arguments)
        batches.append(flow.dispatch(job, adapter, principal, 'demo.' + job + '.dispatch')['batch'])
    # Both durable jobs are dispatched before any observation is accepted.
    flow.ingest(batches[1])
    flow.ingest(batches[0])
    job = 'BackRobot'
    for operation, arguments in [
        ('request', {'job_id': job, 'rack_id': racks[0]['id'],
                     'target_endpoint': racks[0]['initial_endpoint'], 'agent_id': robots[0]['id']}),
        ('reserve', {'job_id': job}), ('prepare', {'job_id': job})]:
        flow.act(operation, principal, 'demo.' + job + '.' + operation, **arguments)
    batch = flow.dispatch(job, robot, principal, 'demo.' + job + '.dispatch')['batch']
    flow.ingest(batch)
    if flow.state['inventory'] != before or any(j['phase'] != 'completed' for j in flow.state['jobs'].values()):
        raise TaskError('Synthetic demo did not preserve inventory or complete all three transports')
    return flow.report()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, help='Shared journal under exports/')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('create', 'demo'):
        child = sub.add_parser(name)
        child.add_argument('--run-id', default='SYN.AsyncTransport.AB.Run')
        child.add_argument('--profile', type=Path)
    for name in ('status', 'report', 'session'):
        child = sub.add_parser(name)
        child.add_argument('run_id')
        if name == 'report':
            child.add_argument('--out', type=Path)
        if name == 'session':
            child.add_argument('--resume', action='store_true')
            child.add_argument('--principal', help='Synthetic fixture principal, not an authenticated login')
            child.add_argument('--request-id')
            child.add_argument('--actions', type=Path, help='JSONL with operation, principal, request_id, args')
    args = parser.parse_args(argv)
    try:
        store = output_path(resolve_store(args.store))
        with Journal(store) as journal:
            if args.command in {'create', 'demo'}:
                flow = AsyncTransport.create(journal, args.run_id, source=args.profile)
                result = run_demo(flow) if args.command == 'demo' else flow.report()
            else:
                flow = AsyncTransport.open(journal, args.run_id)
                if args.command == 'session':
                    if not args.resume:
                        raise TaskError('A new writing session requires explicit --resume and reconciliation')
                    principal = args.principal or flow.state['definition']['owner_principal']
                    flow = AsyncTransport.open(journal, args.run_id, resume=True,
                        principal=principal, request_id=args.request_id or 'resume.' + uuid.uuid4().hex)
                    stream = args.actions.open() if args.actions else sys.stdin
                    try:
                        for line in stream:
                            if not line.strip():
                                continue
                            message = parse_json(line)
                            domain.exact(message, 'operation principal request_id args', 'session message')
                            flow.act(message['operation'], message['principal'],
                                     message['request_id'], **message['args'])
                    finally:
                        if args.actions:
                            stream.close()
                result = flow.report()
            if args.command == 'report' and args.out:
                destination = output_path(args.out)
                if destination.exists():
                    raise TaskError('Use a new report path; original evidence is preserved')
                destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
                print(json.dumps({'report': str(destination), 'run_id': args.run_id}))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (TaskError, ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
