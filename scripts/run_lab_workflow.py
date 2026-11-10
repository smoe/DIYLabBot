"""Local synthetic CF01, NanoDrop and Qubit workflow; no network or hardware."""
import argparse
import inspect
import json
import sqlite3
import sys
import time
from pathlib import Path

from manual_tasks import Journal, TaskError
from manual_workflow import DEFAULT_STORE, resolve_store
from manual_workflow_cli import output_path
from lab_workflow import Workflow, SOURCE
from run_nanodrop_manual import synthetic_report as nanodrop_report
from run_qubit_manual import (begin_preparation, confirm_preparation, measure,
                              prepare_standards, synthetic_report as qubit_report)

ACTOR = 'SYN.Operator01'


def handover(flow):
    flow.handover(ACTOR, observations=flow.inventory_observations(),
                  workspace_clear=True, arm_clear=True, gripper_empty=True)


def run_nanodrop(flow, pause_after_intent=False):
    """Explicit fictitious input generator, separate from validation."""
    handover(flow);stage = flow.stage('nanodrop')
    stage.act('claim', ACTOR)
    stage.act('blank', ACTOR, reference_id='SYN.Blank.Buffer01', cleaned=True)
    for sample_id, sample in stage.state['samples'].items():
        stage.act('take', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                  rack_id=sample['location']['rack_id'], place_id=sample['original_place_id'])
        stage.act('begin_measurement', ACTOR, sample_id=sample_id,
                  measurement_id=stage.state['planned_measurements'][sample_id])
        if pause_after_intent:return
        stage.act('confirm_measurement', ACTOR, intent_id=stage.state['pending_measurement']['intent_id'],
                  observed_sample_id=sample_id,
                  volume_ul=stage.state['definition']['profile']['parameters']['sample_volume_ul'],cleaned=True)
        stage.act('place', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                  rack_id=stage.state['definition']['profile']['rack']['id'],place_id=sample['original_place_id'])
    stage.import_content(nanodrop_report(stage.state), ACTOR, 'synthetic-nanodrop.csv')
    stage.act('review_results', ACTOR, decision='accepted',reason='Explicit synthetic decision; no real QC qualification')
    stage.act('release', ACTOR, workspace_clear=True)


def run_qubit(flow, pause_after_intent=False):
    handover(flow);stage=flow.stage('qubit')
    stage.act('claim', ACTOR);prepare_standards(stage)
    for sample_id,sample in stage.state['samples'].items():
        stage.act('take',ACTOR,sample_id=sample_id,observed_sample_id=sample_id,
                  rack_id=sample['location']['rack_id'],place_id=sample['original_place_id'])
        pending=begin_preparation(stage,'sample',sample_id)
        if pause_after_intent:return
        confirm_preparation(stage)
        preparation_id=stage.state['preparations'][pending['preparation_id']]['id']
        stage.act('place',ACTOR,sample_id=sample_id,observed_sample_id=sample_id,
                  rack_id=stage.state['definition']['profile']['rack']['id'],place_id=sample['original_place_id'])
        stage.act('advance_time',ACTOR,seconds=stage.state['definition']['profile']['parameters']['incubation_min_s'])
        measure(stage,preparation_id)
        vessel_id=pending['vessel_id']
        stage.act('dispose_vessel',ACTOR,vessel_id=vessel_id,observed_vessel_id=vessel_id,
                  reason='Explicit synthetic disposal after one assay measurement')
    for vessel_id,vessel in stage.state['derived_vessels'].items():
        if vessel['location']['kind']!='discarded':
            stage.act('dispose_vessel',ACTOR,vessel_id=vessel_id,observed_vessel_id=vessel_id,
                      reason='Explicit synthetic standard disposal')
    stage.import_content(qubit_report(stage.state),ACTOR,'synthetic-qubit.csv')
    stage.act('review_results',ACTOR,decision='accepted',reason='Explicit synthetic decision; no real analytical qualification')
    stage.act('release',ACTOR,workspace_clear=True)


def run_demo(flow,transport='ros2',pause_after=None):
    """Only this demo supplies invented positive observations and masses."""
    flow.accept_rack(ACTOR,observations=flow.inventory_observations())
    for sample in flow.state['definition']['manifest']['samples']:
        flow.confirm_mass(ACTOR,sample['vessel_id'],mass_g=2.0,content_revision=0)
    flow.run_cf01(ACTOR,transport=transport)
    if pause_after=='cf01':return
    run_nanodrop(flow,pause_after_intent=pause_after=='nanodrop_intent')
    if pause_after=='nanodrop_intent':return
    run_qubit(flow,pause_after_intent=pause_after=='qubit_intent')


def card(flow):
    state=flow.state
    return {'run_id':flow.run_id,'status':state['status'],'active_stage':state['active_stage'],
            'logical_time_s':state['logical_time_s'],'clock_mode':state['clock_mode'],'deadline_s':state['deadline_s'],
            'recovery_required':state['recovery_required'],'resources':state['resources'],
            'stages':{k:{field:v.get(field) for field in ['status','attempt_id','actor_id','deadline_s','recovery_required',
                        'pending_operation','pending_measurement','view']} for k,v in state['stages'].items()},
            'inventory':state['inventory'],'bookings':state['bookings']}


def session(flow,actions=None):
    print(json.dumps(card(flow),ensure_ascii=False))
    stream=Path(actions).open() if actions else sys.stdin
    try:
        for line in stream:
            if not line.strip():continue
            if line.strip()=='quit':break
            if line.strip()=='status':print(json.dumps(card(flow),ensure_ascii=False));continue
            request=json.loads(line)
            command=request['command'];actor=request['actor_id'];data=request.get('data',{})
            if request.get('stage_id'):
                if command=='import_results':
                    flow.stage(request['stage_id']).import_content(Path(request['file']).read_bytes(),actor,Path(request['file']).name)
                else:flow.stage_act(request['stage_id'],command,actor,**data)
            else:
                if command not in {'accept_rack','confirm_mass','run_cf01','handover','advance_time','cancel','finish_cf01_abort','reconcile_initial_cf01','restart_cf01'}:
                    raise TaskError('Unknown root command')
                if command=='run_cf01' and 'configure' in data:
                    raise TaskError('The CLI does not accept test injection callbacks')
                handler=getattr(flow,command)
                try:inspect.signature(handler).bind(actor,**data)
                except TypeError as error:raise TaskError('Invalid root arguments: '+str(error)) from error
                handler(actor,**data)
            print(json.dumps(card(flow),ensure_ascii=False))
            if flow.state['status'] in {'completed','cancelled'}:break
    finally:
        if actions:stream.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,help='Shared store; defaults to workflows.sqlite3 or an existing legacy nanodrop.sqlite3')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ['create','demo']:
        child=sub.add_parser(name);child.add_argument('--profile',type=Path,default=SOURCE);child.add_argument('--run-id')
        if name=='demo':
            child.add_argument('--transport',choices=['ros2','sila2'],default='ros2')
            child.add_argument('--pause-after',choices=['cf01','nanodrop_intent','qubit_intent'])
    for name in ['status','report','session']:
        child=sub.add_parser(name);child.add_argument('run_id')
        if name=='report':child.add_argument('--out',type=Path)
        if name=='session':child.add_argument('--resume',action='store_true');child.add_argument('--actions',type=Path)
    args=parser.parse_args();flow=None
    try:
        with Journal(output_path(resolve_store(args.store))) as journal:
            try:
                if args.command in {'create','demo'}:
                    flow=Workflow.create(journal,args.profile,args.run_id)
                    if args.command=='demo':run_demo(flow,args.transport,args.pause_after)
                    print(json.dumps(card(flow),ensure_ascii=False))
                elif args.command=='session':
                    flow=Workflow.open(journal,args.run_id,resume=args.resume);session(flow,args.actions)
                else:
                    flow=Workflow(journal,args.run_id)
                    if args.command=='status':print(json.dumps(card(flow),ensure_ascii=False))
                    else:
                        report=flow.report();target=output_path(args.out or journal.path.parent/flow.run_id/'report.json')
                        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                        print(json.dumps({'report':str(target),'passed':report['passed']}))
            finally:
                if flow:flow.close()
    except (TaskError,ValueError,KeyError,OSError,sqlite3.Error) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
