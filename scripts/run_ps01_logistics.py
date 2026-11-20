"""Run or inspect the persistent PS01/TR01 synthetic logistics fixture."""
import argparse
import json
from pathlib import Path
import uuid

from manual_tasks import Journal
from ps01_logistics import Logistics, ROOT, VARIANTS, forecast


def clear_stations(flow, prefix):
    for station in ('PS01', 'RF02'):
        flow.act('access', prefix + '.' + station, station=station, workspace_clear=True,
                 pipetting_parked=True, transfer_parked=True, evidence='test_fixture')


def complete_mock(flow, job):
    batch = flow.dispatch_mock(job, 'Dispatch.' + job)
    flow.ingest_mock(batch)


def demo(flow):
    flow.act('admit', 'Admit', evidence='test_fixture')
    clear_stations(flow, 'Clear')
    # Whole rack out and back; both original vessel/slot identities persist.
    for job, target, mobile in [('RackOut', 'RF02.InfeedRack', True),
                                ('RackReturnStage', 'RF02.Outfeed', False),
                                ('RackReturn', 'PS01.InfeedRack', True)]:
        flow.act('transfer', 'Prepare.' + job, carrier_id='Carrier.Rack01', target=target, job_id=job, mobile=mobile)
        complete_mock(flow, job)
    destinations={'tip_10_ul':['PS01.S04'],'tip_200_ul':['PS01.S05','PS01.S09'],'tip_1000_ul':['PS01.S07']}
    for variant in VARIANTS:
        demand = 'Supply.' + variant
        flow.act('request_tips', 'Request.' + demand, demand_id=demand, station='PS01',
                 variant=variant, boxes=len(destinations[variant]), reason='Synthetic replenishment example; two 200-uL boxes cover the matrix deficit')
        for index,target in enumerate(destinations[variant]):
            for stage in ('Stage','Deliver'):
                job=demand+'.'+str(index)+'.'+stage
                result = flow.act('serve', 'Schedule.' + job, demand_id=demand, job_id=job)
                if result['job_id'] is None:
                    raise RuntimeError('Demo supply blocked: ' + str(result))
                complete_mock(flow, result['job_id'])
            received=result['carrier_id'];job=demand+'.'+str(index)+'.Seat'
            flow.act('transfer', 'Prepare.' + job, carrier_id=received, target=target, job_id=job, mobile=False)
            complete_mock(flow, job)
    return flow.report()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('demo', 'init', 'status', 'forecast', 'resume', 'act', 'mock-complete'))
    parser.add_argument('--store', type=Path, default=ROOT / 'exports/ps01-logistics/journal.sqlite')
    parser.add_argument('--run-id')
    parser.add_argument('--operation')
    parser.add_argument('--request-id')
    parser.add_argument('--arguments', type=Path, help='JSON arguments; confirmations are explicit test-fixture inputs')
    parser.add_argument('--session', help='Session returned by init/resume; required for later mutations')
    parser.add_argument('--job-id')
    parser.add_argument('--station', default='PS01')
    args = parser.parse_args()
    args.store = args.store.resolve()
    if not args.store.is_relative_to(ROOT / 'exports'):
        parser.error('Runtime stores must be private local exports/ files')
    args.store.parent.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or ('Logistics.' + uuid.uuid4().hex if args.command in ('demo', 'init') else None)
    if not run_id:
        parser.error('--run-id required')
    with Journal(args.store) as journal:
        if args.command in ('demo', 'init'):
            flow = Logistics.create(journal, run_id)
            result = demo(flow) if args.command == 'demo' else {'run_id': run_id, 'session': flow.session}
        elif args.command == 'resume':
            flow = Logistics.open(journal, run_id, resume=True)
            result = {'run_id': run_id, 'session': flow.session, 'report': flow.report()}
        else:
            flow = Logistics(journal, run_id, args.session)
            if args.command == 'status':
                result = flow.report()
            elif args.command == 'forecast':
                result = forecast(flow.state, args.station)
            elif args.command == 'mock-complete':
                if not args.job_id:
                    parser.error('--job-id required')
                complete_mock(flow, args.job_id); result = flow.report()
            else:
                if not args.operation or not args.request_id or not args.arguments:
                    parser.error('--operation, --request-id and --arguments required')
                result = flow.act(args.operation, args.request_id, **json.loads(args.arguments.read_text()))
        report = args.store.parent / (run_id + '.report.json')
        report.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        print(json.dumps({'run_id': run_id, 'report': str(report), **({'session': flow.session} if args.command in ('init', 'resume') else {})}))


if __name__ == '__main__':
    main()
