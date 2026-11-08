"""Run the synthetic rack -> CF01 -> original rack slots communication fixture."""
import argparse
import json
from pathlib import Path
from cf01_rack_batch import Runner, BatchError, ROOT
from datetime import datetime, timezone


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport',choices=['ros2','sila2'],default='ros2',help='Local contract decoding only; no network server')
    parser.add_argument('--out',type=Path,default=None)
    args=parser.parse_args()
    try:report=Runner(transport=args.transport).run()
    except BatchError as error:report=error.report
    if args.out is None:args.out=ROOT/'exports/generated'/('cf01-rack-batch-'+report['effective_profile_sha256'][:12])/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+args.transport+'.json')
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','mode','order_restored','spin_completed','network_executed','hardware_executed']}))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
