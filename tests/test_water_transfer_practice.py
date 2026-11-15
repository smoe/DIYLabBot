"""Water-only semantics, no replay after lost receipt, and shared-journal atomicity."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from manual_tasks import Journal,TaskError
from manual_workflow import ObservationError
from cutrun_manual_workflow import CutRunManualWorkflow
from material_workflow import MaterialWorkflow
from water_transfer_practice import WaterPractice,definition,protocol
from run_water_transfer_practice import FixtureClock,fixture_inventory,fixture_post_inventory,run_demo


class WaterPracticeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'water.sqlite3';self.journal=Journal(self.path);self.addCleanup(self.journal.close)
        self.clock=FixtureClock();self.inventory=fixture_inventory('SYN.Water.Test');self.actor=self.inventory['actors'][0]
        self.flow=WaterPractice.create(self.journal,self.inventory,'SYN.Water.Test',mode='test_fixture',clock_provider=self.clock);self.n=0
        self.send('accept_inventory',observations=self.flow.inventory_observations());self.send('workspace_clear',confirmed=True);self.send('claim')
    def envelope(self):
        self.n+=1;return {'observation_id':'Test.Obs.'+str(self.n),'source_kind':'test_fixture','observed_at':None,'source_ref':'Explicit water test fixture','artifact_sha256':None}
    def send(self,command,**data):
        self.clock.seconds+=1;return self.flow.act(command,self.actor,observation=self.envelope(),**data)
    def begin(self,step='A1',intent=None):
        intent=intent or 'Test.Intent.'+step;self.send('begin_transfer',step_id=step,intent_id=intent);return intent
    def normal(self,step):
        intent=self.begin(step);self.send('confirm_transfer',intent_id=intent,actual_volume_ul=100,target_total_ul=100,reason='Invented observed water transfer');return intent
    def before_fault(self):
        for step in ('A1','B1','C1'):self.normal(step)
        return self.begin('A2')
    def resolve(self,intent,**overrides):
        data={'intent_id':intent,'outcome':'performed','actual_volume_ul':100,'target_total_ul':200,
              'observations':fixture_post_inventory(self.flow,intent,100,200),'workspace_clear':True,'reason':'Explicit fixture reconciliation without another transfer'}
        data.update(overrides);self.send('resolve_transfer',**data)

    def test_full_demo_conserves_water_and_runs_four_transfers_without_replay(self):
        with Journal(Path(self.temp.name)/'demo.sqlite3') as journal:r=run_demo(journal,'SYN.Water.Full')
        self.assertTrue(r['practice_completed']);self.assertEqual(r['mode'],'test_fixture');self.assertEqual(r['recorded_current_water_total_ul'],600)
        self.assertEqual(len(r['bookings']),4);self.assertEqual(len({v['material_id'] for v in r['material_allocations'].values()}),3)
        self.assertEqual(r['demo_evidence']['simulated_transfers'],['A1','B1','C1','A2']);self.assertFalse(r['demo_evidence']['additional_transfer_during_reconciliation'])
        checkpoint=r['demo_evidence']['missing_receipt_checkpoint'];self.assertEqual(checkpoint['outcome'],'unknown');self.assertTrue(checkpoint['resources_held']);self.assertTrue(checkpoint['stale_session_and_blind_replay_blocked'])
        self.assertFalse(r['reference_success']);self.assertFalse(r['hardware_executed']);self.assertFalse(r['biochemical_protocol_executed']);self.assertFalse(r['elapsed_time_qualified'])

    def test_sequence_generic_commands_and_fault_receipt_cannot_be_bypassed(self):
        before=self.flow.state
        with self.assertRaises(TaskError):self.begin('B1')
        with self.assertRaises(TaskError):self.send('begin_effect')
        with self.assertRaises(TaskError):self.send('begin_activation')
        self.assertEqual(self.flow.state,before)
        intent=self.before_fault();before=self.flow.state
        with self.assertRaises(TaskError):self.send('confirm_transfer',intent_id=intent,actual_volume_ul=100,target_total_ul=200,reason='Skipping the fault')
        self.assertEqual(self.flow.state,before)

    def test_unknown_transfer_blocks_new_intents_and_never_becomes_zero(self):
        intent=self.before_fault();self.send('mark_unknown',intent_id=intent,reason='Lost receipt')
        self.assertIsNone(self.flow.report()['recorded_current_water_total_ul'])
        before=self.flow.state;owners=self.journal.owners()
        with self.assertRaises(TaskError):self.begin('A2','Never.Redose')
        with self.assertRaises(TaskError):self.send('close_practice',workspace_clear=True,reason='Premature completion')
        self.assertEqual(self.flow.state,before);self.assertEqual(self.journal.owners(),owners)
        self.resolve(intent);self.assertEqual(self.flow.report()['recorded_current_water_total_ul'],600);self.assertEqual(len(self.flow.state['bookings']),4)

    def test_observation_replay_is_idempotent_and_conflicting_reuse_writes_nothing(self):
        intent=self.begin();obs=self.envelope();data={'intent_id':intent,'actual_volume_ul':100,'target_total_ul':100,'reason':'One receipt'}
        self.flow.act('confirm_transfer',self.actor,observation=obs,**data)
        before=self.flow.state;revision=len(self.journal.history(self.flow.run_id))
        self.flow.act('confirm_transfer',self.actor,observation=obs,**data)
        self.assertEqual(len(self.journal.history(self.flow.run_id)),revision)
        with self.assertRaises(TaskError):self.flow.act('confirm_transfer',self.actor,observation=obs,**{**data,'actual_volume_ul':101})
        self.assertEqual(self.flow.state,before)

    def test_bad_quantity_or_inventory_is_durable_but_does_not_debit_or_advance(self):
        intent=self.begin();before=copy.deepcopy(self.flow.state['bookings'])
        with self.assertRaises(ObservationError):self.send('confirm_transfer',intent_id=intent,actual_volume_ul=100,target_total_ul=99,reason='Disagreement')
        self.assertEqual(self.flow.state['bookings'],before);self.assertEqual(self.journal.history(self.flow.run_id)[-1]['kind'],'observation_rejected')
        self.assertTrue(self.flow.state['recovery_required'])
        with self.assertRaises(ObservationError):
            self.send('resolve_transfer',intent_id=intent,outcome='performed',actual_volume_ul=100,target_total_ul=100,observations=[],workspace_clear=True,reason='Missing inventory')
        self.assertEqual(self.flow.state['bookings'],before)

    def test_failed_event_commit_rolls_back_booking_materials_and_observation(self):
        intent=self.begin();before=self.flow.state;revision=len(self.journal.history(self.flow.run_id));original=self.journal._event
        def fail(*a,**kw):original(*a,**kw);raise OSError('Fixture disk failure after event insert')
        with patch.object(self.journal,'_event',side_effect=fail),self.assertRaises(OSError):
            self.send('confirm_transfer',intent_id=intent,actual_volume_ul=100,target_total_ul=100,reason='Fixture receipt')
        self.assertEqual(self.flow.state,before);self.assertEqual(len(self.journal.history(self.flow.run_id)),revision)

    def test_hard_exit_preserves_uncertain_transfer_and_fences_old_session(self):
        intent=self.before_fault();old=self.flow
        script='''import os,sys
sys.path.insert(0,sys.argv[1])
from manual_tasks import Journal
from water_transfer_practice import WaterPractice
from run_water_transfer_practice import FixtureClock
with Journal(sys.argv[2]) as j:
 f=WaterPractice.open(j,sys.argv[3],resume=True,clock=FixtureClock())
 f.act('mark_unknown',sys.argv[4],intent_id=sys.argv[5],reason='Fixture missing acknowledgement before hard exit',observation={'observation_id':'Crash.Obs','source_kind':'test_fixture','observed_at':None,'source_ref':'crash fixture','artifact_sha256':None})
 os._exit(23)
'''
        result=subprocess.run([sys.executable,'-B','-c',script,str(ROOT/'scripts'),str(self.path),self.flow.run_id,self.actor,intent],capture_output=True,text=True)
        self.assertEqual(result.returncode,23,result.stderr)
        self.flow=WaterPractice.open(self.journal,self.flow.run_id,resume=True,clock=self.clock)
        self.assertEqual(self.flow.state['bookings'][intent]['outcome'],'unknown');self.assertTrue(self.journal.owners())
        with self.assertRaises(TaskError):old.act('begin_transfer',self.actor,observation=self.envelope(),step_id='A2',intent_id='Stale.Replay')
        with self.assertRaises(TaskError):self.begin('A2','Current.Replay')
        self.resolve(intent);self.assertEqual(len(self.flow.state['bookings']),4)

    def test_nonperformance_requires_explicit_retry_not_implicit_advance(self):
        intent=self.before_fault();self.send('mark_unknown',intent_id=intent,reason='Unknown')
        self.send('resolve_transfer',intent_id=intent,outcome='not_performed',observations=self.flow.inventory_observations(),workspace_clear=True,reason='Explicitly observed no transfer')
        self.assertFalse(self.flow.report()['steps'][-1]['completed'])
        retry=self.begin('A2','Explicit.Retry');self.send('mark_unknown',intent_id=retry,reason='Receipt exercise on explicit new attempt');self.resolve(retry)
        self.assertEqual(self.flow.state['bookings'][intent]['outcome'],'not_performed');self.assertEqual(self.flow.report()['recorded_current_water_total_ul'],600)

    def test_initial_water_declarations_modes_and_closed_engines_are_enforced(self):
        for field,value in [('medium','DNA'),('actors',[])]:
            bad=copy.deepcopy(self.inventory);bad[field]=value
            with self.assertRaises(TaskError):definition(bad,'test_fixture',json.dumps(bad).encode())
        for value in (None,True,float('nan'),-1,0):
            bad=copy.deepcopy(self.inventory);bad['paths']['A']['initial_volume_ul']=value
            with self.assertRaises(TaskError):definition(bad,'test_fixture',json.dumps(bad).encode())
        with self.assertRaises(TaskError):WaterPractice.create(self.journal,self.inventory,'SYN.Bad.Manual')
        for cls in (MaterialWorkflow,CutRunManualWorkflow):
            with self.assertRaises(TaskError):cls(self.journal,self.flow.run_id,None)
        self.assertFalse(any(name.startswith('model/cutrun') for name in self.flow.state['definition']['source_files_sha256']))

    def test_sources_cannot_be_reintroduced_or_runtime_changed_for_a_writer(self):
        with self.assertRaises(TaskError):WaterPractice.create(self.journal,self.inventory,'SYN.Another.Run',mode='test_fixture',clock_provider=self.clock)
        with patch('cutrun_manual_workflow.digest',return_value='changed'):
            with self.assertRaisesRegex(TaskError,'Runtime source changed'):WaterPractice(self.journal,self.flow.run_id,self.flow.session)
        self.assertTrue(self.flow.state['resources'])


class WaterCliTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'exports').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='water-cli-tests-',dir=ROOT/'exports');self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name);self.store=self.dir/'water.sqlite3';self.counter=0
    def cli(self,*args,success=True):
        r=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/run_water_transfer_practice.py'),'--store',str(self.store),*args],capture_output=True,text=True)
        self.assertEqual(r.returncode,0 if success else 1,r.stdout+r.stderr);return json.loads(r.stdout)
    def send(self,action,session,**data):
        self.counter+=1;path=self.dir/'observation.json';path.write_text(json.dumps({'observation_id':'Cli.Obs.'+str(self.counter),'source_kind':'test_fixture','observed_at':None,'source_ref':'Explicit manual-CLI test, no physical action','artifact_sha256':None}))
        return self.cli('act','WATER.CLI.TEST','--session',session,'--actor','Test.Operator','--action',action,'--observation',str(path),'--data',json.dumps(data))
    def test_prepare_does_not_create_store_or_fill_manual_values(self):
        result=self.cli('prepare');self.assertFalse(self.store.exists());self.assertFalse(result['manual_ready'])
        self.assertTrue(all(b['initial_volume_ul'] is None for b in result['inventory_template']['paths'].values()))
        self.assertEqual(set(result['action_arguments']['begin_transfer']),{'step_id','intent_id'})
        self.assertTrue(result['action_arguments']['resolve_transfer']['observations']['required'])
    def test_manual_cli_session_cross_process_reads_and_inventory_reconciliation(self):
        inventory=fixture_inventory('WATER.CLI.TEST');inventory['actors']=['Test.Operator'];path=self.dir/'inventory.json';path.write_text(json.dumps(inventory))
        created=self.cli('create','--inventory',str(path),'--run-id','WATER.CLI.TEST');session=created['session'];state=created['state']
        observations=[{'vessel_id':i,'material_ids':[k for k,m in state['inventory']['materials'].items() if m['vessel_id']==i],'location':v['location']} for i,v in state['inventory']['vessels'].items()]
        self.send('accept_inventory',session,observations=observations);self.send('workspace_clear',session,confirmed=True);self.send('claim',session)
        self.send('begin_transfer',session,step_id='A1',intent_id='Manual.A1')
        state=self.send('confirm_transfer',session,intent_id='Manual.A1',actual_volume_ul=100,target_total_ul=100,reason='Explicit CLI fixture observation')
        with Journal(self.store) as j:revision=len(j.history('WATER.CLI.TEST'))
        status=self.cli('status','WATER.CLI.TEST');self.assertEqual(status['mode'],'manual_observation');self.assertFalse(status['practice_completed'])
        report=self.cli('report','WATER.CLI.TEST');self.assertFalse(report['elapsed_time_qualified']);self.assertFalse(report['physical_execution_verified'])
        with Journal(self.store) as j:self.assertEqual(len(j.history('WATER.CLI.TEST')),revision)
        opened=self.cli('resume','WATER.CLI.TEST');self.assertNotEqual(opened['session'],session)
        observation=self.dir/'old.json';observation.write_text(json.dumps({'observation_id':'Old.Session','source_kind':'test_fixture','observed_at':None,'source_ref':'CLI fixture','artifact_sha256':None}))
        self.cli('act','WATER.CLI.TEST','--session',session,'--actor','Test.Operator','--action','workspace_clear','--observation',str(observation),'--data','{"confirmed":true}',success=False)
        observations=[{'vessel_id':i,'material_ids':[k for k,m in state['inventory']['materials'].items() if m['vessel_id']==i],'location':v['location']} for i,v in state['inventory']['vessels'].items()]
        self.send('reconcile',opened['session'],observations=observations,workspace_clear=True,reason='Explicit fixture inventory agreement after CLI resume')
        self.send('begin_transfer',opened['session'],step_id='B1',intent_id='Manual.B1')


if __name__=='__main__':unittest.main()
