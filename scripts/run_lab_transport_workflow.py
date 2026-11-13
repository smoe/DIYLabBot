"""Opt-in CF01/NanoDrop/Qubit workflow with synthetic asynchronous beam transport."""
import argparse
import inspect
import json
from pathlib import Path
import sqlite3
import sys

import async_transport_domain as domain
from async_transport_adapters import HumanTeleportMock, RobotTeleportMock
from lab_transport_sources import SOURCE
from lab_transport_workflow import TransportWorkflow
from manual_tasks import Journal, TaskError
from manual_workflow import resolve_store
from manual_workflow_cli import output_path
from run_lab_workflow import ACTOR, card as lab_card, run_nanodrop, run_qubit


def dispatch_route(flow, route_id, job_id):
    """Only the demo supplies invented, positive endpoint/agent observations."""
    flow.prepare_transport(ACTOR, route_id, job_id, 'demo.' + job_id + '.prepare')
    topology = flow.state['definition']['transport']['topology']
    route = next(item for item in flow.state['definition']['transport']['routes'] if item['id'] == route_id)
    agent = next(item for item in topology['agents'] if item['id'] == route['agent_id'])
    adapter = (HumanTeleportMock(agent['id']) if agent['kind'] == 'human' else
               RobotTeleportMock(agent['id'], order=('delivery_accept', 'delivery_release',
                                                     'pickup_accept', 'pickup_release')))
    return flow.dispatch_transport(job_id, adapter, ACTOR, 'demo.' + job_id + '.dispatch')['batch']


def run_demo(flow):
    flow.accept_rack(ACTOR, observations=flow.inventory_observations())
    for sample in flow.state['definition']['manifest']['samples']:
        flow.confirm_mass(ACTOR, sample['vessel_id'], mass_g=2.0, content_revision=0)
    flow.run_cf01(ACTOR)
    batch = dispatch_route(flow, 'CF01ToNanoDrop', 'ToNanoDrop')
    flow.ingest_transport(batch)
    awaiting = []

    def before_import(current):
        awaiting.extend(dispatch_route(current, 'NanoDropToQubit', 'ToQubit'))

    # All twelve measured originals are back in their existing Rack/Slot01–12.
    # Transport remains open while the existing ND import/review/release run.
    run_nanodrop(flow, before_import=before_import)
    state = flow.state
    if state['stages']['nanodrop']['status'] != 'completed' or not awaiting:
        raise TaskError('Demo did not perform independent NanoDrop result handling')
    if state['transport']['jobs']['ToQubit']['phase'] == 'completed':
        raise TaskError('Demo accepted transport without explicit receipt ingestion')
    flow.ingest_transport(awaiting)
    run_qubit(flow)
    report = flow.report()
    if not report['passed']:
        raise TaskError('The synthetic transport workflow is not fully resolved')
    return report


def card(flow):
    state = flow.state
    return {**lab_card(flow), 'transport': state['transport'],
            'transport_bindings': state['transport_bindings']}


def session(flow, actions):
    """Explicit local messages; no background dispatcher or authenticated service."""
    stream = Path(actions).open() if actions else sys.stdin
    try:
        for line in stream:
            if not line.strip(): continue
            request = domain._json(line)
            required = {'command', 'actor_id', 'data'}
            if not isinstance(request, dict) or set(request) not in (required, required | {'stage_id'}):
                raise TaskError('Exact command, actor_id, data and optional stage_id required')
            actor = domain.ident(request['actor_id'])
            data = request['data']
            if not isinstance(data, dict): raise TaskError('Explicit command data required')
            command = request['command']
            if 'stage_id' in request:
                flow.stage_act(request['stage_id'], command, actor, **data)
            elif command == 'transport_act':
                domain.exact(data, 'operation request_id args', 'transport action')
                flow.transport_act(data['operation'], actor, data['request_id'], **data['args'])
            else:
                allowed = {'accept_rack', 'confirm_mass', 'run_cf01', 'handover', 'advance_time',
                           'cancel', 'finish_cf01_abort', 'reconcile_initial_cf01', 'restart_cf01',
                           'prepare_transport'}
                if command not in allowed or (command == 'run_cf01' and 'configure' in data):
                    raise TaskError('Unsupported local workflow command')
                handler = getattr(flow, command)
                try: inspect.signature(handler).bind(actor, **data)
                except TypeError as error: raise TaskError('Invalid command arguments: ' + str(error)) from error
                handler(actor, **data)
            print(json.dumps(card(flow), ensure_ascii=False, allow_nan=False))
    finally:
        if actions: stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('create', 'demo'):
        child = sub.add_parser(name)
        child.add_argument('--profile', type=Path, default=SOURCE)
        child.add_argument('--run-id', default='SYN.LAB.AsyncTransport')
    for name in ('status', 'report', 'session'):
        child = sub.add_parser(name)
        child.add_argument('run_id')
        if name == 'report': child.add_argument('--out', type=Path)
        if name == 'session':
            child.add_argument('--resume', action='store_true')
            child.add_argument('--actions', type=Path)
    args = parser.parse_args(argv)
    flow = None
    try:
        with Journal(output_path(resolve_store(args.store))) as journal:
            try:
                if args.command in {'create', 'demo'}:
                    flow = TransportWorkflow.create(journal, args.profile, args.run_id)
                    result = run_demo(flow) if args.command == 'demo' else card(flow)
                elif args.command == 'session':
                    if not args.resume: raise TaskError('Writing sessions require explicit --resume')
                    flow = TransportWorkflow.open(journal, args.run_id, resume=True)
                    session(flow, args.actions)
                    result = card(flow)
                else:
                    flow = TransportWorkflow(journal, args.run_id)
                    result = card(flow) if args.command == 'status' else flow.report()
                if args.command == 'report' and args.out:
                    destination = output_path(args.out)
                    with destination.open('x', encoding='utf-8') as stream:
                        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
                    print(json.dumps({'report': str(destination), 'passed': result['passed']}))
                else:
                    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            finally:
                if flow: flow.close()
        return 0
    except (TaskError, ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
