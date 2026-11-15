"""Manual water practice and a labelled software demo; never operate equipment."""
import copy
import inspect
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from manual_tasks import Journal, TaskError
from manual_workflow import ROOT, resolve_store
from run_material_lifecycle import Parser, runtime_path, report_path
from water_transfer_practice import WaterPractice, protocol, FIXTURE


class FixtureClock:
    """Explicit test time, never installed for manual practice by the CLI."""
    def __init__(self): self.seconds=0
    def sample(self):
        return {'format':'solidcraftbot.clock-observation/1','source_kind':'test_clock',
            'clock_id':'water-fixture-clock','process_id':'water-fixture-writer',
            'utc':(datetime(2026,11,15,tzinfo=timezone.utc)+timedelta(seconds=self.seconds)).isoformat().replace('+00:00','Z'),
            'monotonic_ns':self.seconds*1000000000,'uncertainty_s':0,'suspend_policy':'inclusive'}


def fixture_inventory(run_id):
    fixture=json.loads((ROOT/FIXTURE).read_text())
    if fixture['format']!='solidcraftbot.water-transfer-practice-fixture/1' or fixture['mode']!='test_fixture':
        raise TaskError('Explicit water test fixture required')
    return {'format':'solidcraftbot.water-transfer-inventory/1','medium':'water','actors':['SYN.Water.Operator'],
        'paths':{p:{'source_material_id':run_id+'.WaterSource.'+p,'source_vessel_id':run_id+'.SourceTube.'+p,
            'target_vessel_id':run_id+'.TargetTube.'+p,
            'source_location':{'kind':'rack','rack_id':run_id+'.Rack','place_id':'Source'+p},
            'target_location':{'kind':'rack','rack_id':run_id+'.Rack','place_id':'Target'+p},
            'initial_volume_ul':fixture['initial_volume_ul'],'transfer_volume_ul':fixture['transfer_volume_ul']} for p in 'ABC'}}


def fixture_post_inventory(flow,intent_id,actual_volume_ul,target_total_ul):
    """Invent a complete fixture observation; never used by manual CLI actions."""
    if flow.state['definition']['profile']['mode']!='test_fixture':raise TaskError('Only the software fixture may synthesize inventory observations')
    proposal=copy.deepcopy(flow.state)
    flow._receipt(proposal,proposal['actor_id'],intent_id,actual_volume_ul,target_total_ul,'Fixture inventory prediction, not physical evidence')
    return [{'vessel_id':identity,'material_ids':[k for k,m in proposal['inventory']['materials'].items() if m['vessel_id']==identity],
             'location':copy.deepcopy(vessel['location'])} for identity,vessel in proposal['inventory']['vessels'].items()]


def run_demo(journal,run_id=None):
    identity=run_id or 'SYN.WATER.'+uuid.uuid4().hex[:10]
    provider=FixtureClock();inventory=fixture_inventory(identity)
    flow=WaterPractice.create(journal,inventory,identity,mode='test_fixture',clock_provider=provider)
    actor=inventory['actors'][0];counter=0
    def send(command,**data):
        nonlocal counter
        counter+=1;provider.seconds+=1
        return flow.act(command,actor,observation={'observation_id':identity+'.Obs'+str(counter),
            'source_kind':'test_fixture','observed_at':None,'source_ref':'water software fixture','artifact_sha256':None},**data)
    send('accept_inventory',observations=flow.inventory_observations());send('workspace_clear',confirmed=True);send('claim')
    transfers=[];checkpoint=None
    for step in protocol()['steps']:
        intent=identity+'.'+step['id'];binding=inventory['paths'][step['path']];dose=binding['transfer_volume_ul']
        target_total=dose*(2 if step['id']=='A2' else 1)
        send('begin_transfer',step_id=step['id'],intent_id=intent)
        # The fixture models one water transfer, independently of its acknowledgement.
        transfers.append(step['id'])
        if not step['missing_receipt_exercise']:
            send('confirm_transfer',intent_id=intent,actual_volume_ul=dose,target_total_ul=target_total,reason='Invented water transfer observation')
        else:
            send('mark_unknown',intent_id=intent,reason='Fixture: transfer occurred; acknowledgement was not recorded')
            checkpoint={'pending_operation':flow.state['pending_operation'],'outcome':flow.state['bookings'][intent]['outcome'],
                'resources_held':bool(flow.state['resources']),'simulated_transfers':list(transfers)}
            stale=flow
            flow=WaterPractice.open(journal,identity,resume=True,clock=provider)
            blocked=0
            for candidate in (stale,flow):
                try:candidate.act('begin_transfer',actor,observation={'observation_id':'BlockedReplay','source_kind':'test_fixture','observed_at':None,'source_ref':'negative fixture','artifact_sha256':None},step_id='A2',intent_id=identity+'.NeverReplay')
                except TaskError:blocked+=1
            if blocked!=2:raise TaskError('The fixture did not fence the old session and block blind replay')
            checkpoint['stale_session_and_blind_replay_blocked']=True
            observations=fixture_post_inventory(flow,intent,dose,target_total)
            send('resolve_transfer',intent_id=intent,outcome='performed',actual_volume_ul=dose,target_total_ul=target_total,
                 observations=observations,workspace_clear=True,reason='Explicit fixture reconciliation; no second water transfer')
    for material_id,m in flow.state['inventory']['materials'].items():
        if m['disposition']!='consumed':send('set_disposition',material_id=material_id,disposition='retained',reason='Explicit fixture handover')
    send('confirm_inventory',observations=flow.inventory_observations())
    send('close_practice',workspace_clear=True,reason='Three fixture paths and missing-acknowledgement exercise completed')
    report=flow.report();report['demo_evidence']={'simulated_transfers':transfers,'simulated_transfer_count':len(transfers),
        'missing_receipt_checkpoint':checkpoint,'additional_transfer_during_reconciliation':False,
        'scope':'Invented test fixture, not real water or device execution'}
    return report


def main(argv=None):
    parser=Parser(description=__doc__);parser.add_argument('--store',type=Path)
    sub=parser.add_subparsers(dest='command',required=True,parser_class=Parser)
    sub.add_parser('prepare',help='Read-only protocol and unfilled manual inventory template; no store')
    demo=sub.add_parser('demo',help='Run only the explicit software fixture');demo.add_argument('--run-id');demo.add_argument('--out',type=Path)
    create=sub.add_parser('create',help='Start a manual technical record with explicit actual water declarations')
    create.add_argument('--inventory',type=Path,required=True);create.add_argument('--run-id')
    for name in ('status','report','resume','act'):
        p=sub.add_parser(name);p.add_argument('run_id');p.add_argument('--out',type=Path)
        if name=='act':
            p.add_argument('--session',required=True);p.add_argument('--actor',required=True);p.add_argument('--action',required=True)
            p.add_argument('--observation',type=Path,required=True);p.add_argument('--data',default='{}');p.add_argument('--artifact',type=Path)
    try:
        args=parser.parse_args(argv);target=report_path(args.out) if getattr(args,'out',None) else None
        if args.command=='prepare':
            result={'protocol':protocol(),'inventory_template':json.loads((ROOT/'model/water-transfer-practice.inventory.json').read_text()),
                    'manual_ready':False,'e4_decisions_modified':False,
                    'action_arguments':{name:{p.name:{'required':p.default is inspect.Parameter.empty,**({} if p.default is inspect.Parameter.empty else {'default':p.default})} for p in inspect.signature(getattr(WaterPractice,'_'+name)).parameters.values() if p.name not in {'self','state','actor_id'}} for name in sorted(set(WaterPractice.STEPS)|{'reconcile','cancel','finish_cancel'})}}
        else:
            store=runtime_path(resolve_store(args.store))
            if target==store:raise TaskError('Report cannot overwrite journal')
            if args.command not in ('create','demo') and not store.is_file():raise TaskError('Existing water journal required')
            with Journal(store) as journal:
                if args.command=='demo':result=run_demo(journal,args.run_id)
                elif args.command=='create':
                    raw=args.inventory.read_bytes();flow=WaterPractice.create(journal,json.loads(raw),args.run_id,inventory_bytes=raw)
                    result={'run_id':flow.run_id,'session':flow.session,'state':flow.state}
                elif args.command=='resume':
                    flow=WaterPractice.open(journal,args.run_id,resume=True);result={'run_id':flow.run_id,'session':flow.session,'state':flow.state}
                elif args.command=='act':
                    data=json.loads(args.data)
                    if not isinstance(data,dict):raise TaskError('Action data must be an object')
                    result=WaterPractice(journal,args.run_id,args.session).act(args.action,args.actor,
                        observation=json.loads(args.observation.read_bytes()),artifact=args.artifact.read_bytes() if args.artifact else None,**data)
                else:
                    result=WaterPractice(journal,args.run_id,None).report()
                    if args.command=='status':result={k:result[k] for k in ('run_id','mode','status','practice_completed','steps','pending_operation','recovery_required','reference_success')}
        content=json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
        if target:
            with target.open('x') as f:f.write(content)
        print(content,end='');return 0
    except (TaskError,ValueError,TypeError,KeyError,OSError,sqlite3.Error) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
