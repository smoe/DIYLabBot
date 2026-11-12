"""T1 journal atomicity, restart fencing and durable synthetic transport tests."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier, Event
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from async_transport import AsyncTransport
import async_transport_domain as domain
from async_transport_adapters import HumanTeleportMock, RobotTeleportMock
from manual_tasks import Journal, TaskError, digest, encoded

OWNER = 'SYN.Async.Owner'
RUN = 'SYN.Async.RuntimeTest'


class AsyncTransportTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'exports').mkdir(exist_ok=True)
        folder = tempfile.TemporaryDirectory(prefix='async-runtime-test-', dir=ROOT/'exports')
        self.addCleanup(folder.cleanup); self.folder = Path(folder.name)
        self.path = self.folder/'journal.sqlite3'; self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.flow = AsyncTransport.create(self.journal, RUN)
        self.counter = 0

    def act(self, operation, **args):
        self.counter += 1
        return self.flow.act(operation, OWNER, 'Request.'+str(self.counter), **args)

    def prepare(self, job='Job01', rack='SYN.Async.Rack01', target='LabB.S1', agent='AgentHuman'):
        if not self.flow.state['admitted']: self.act('admit')
        self.act('request', job_id=job, rack_id=rack, target_endpoint=target, agent_id=agent)
        self.act('reserve', job_id=job); self.act('prepare', job_id=job)

    def test_creation_is_unadmitted_and_admission_atomically_reserves_actual_inventory(self):
        state = self.flow.state
        self.assertFalse(state['admitted']); self.assertEqual(state['inventory'], {})
        self.assertEqual(state['resources'], []); self.assertEqual(self.journal.owners(), {})
        self.assertTrue(set(('scripts/async_transport.py','scripts/async_transport_adapters.py','scripts/run_async_transport.py')) <= set(state['definition']['source_files_sha256']))
        self.act('admit'); state = self.flow.state
        self.assertTrue(state['admitted'])
        self.assertEqual({name for name,owner in self.journal.owners().items()if owner==RUN}, set(state['resources']))
        self.assertIn('place:SYN.Site01|LabA|LabA.Handover|S1',state['resources'])
        self.assertIsNone(state['inventory']['materials']['SYN.Async.Material02']['initial_quantity']['value'])
        self.assertEqual(state['bookings'], {})

    def test_unadmitted_root_cannot_introduce_jobs_or_reset_its_initial_event(self):
        before = self.journal.history(RUN)
        with self.assertRaises(TaskError): self.act('request',job_id='Job',rack_id='SYN.Async.Rack01',target_endpoint='LabB.S1',agent_id='AgentHuman')
        with self.assertRaises(TaskError): AsyncTransport.create(self.journal,RUN)
        self.assertEqual(self.journal.history(RUN),before)

    def test_request_replay_is_durable_detached_and_rejects_different_principal_or_arguments(self):
        first = self.flow.act('admit',OWNER,'StableRequest'); count=len(self.journal.history(RUN))
        duplicate = self.flow.act('admit',OWNER,'StableRequest')
        self.assertEqual(first,duplicate); self.assertEqual(len(self.journal.history(RUN)),count)
        duplicate['result']['admitted']=False
        self.assertTrue(self.flow.state['requests']['StableRequest']['result']['admitted'])
        for operation,principal,args in [('admit','Other',{}),('admit',OWNER,{'extra':1}),('request',OWNER,{})]:
            with self.assertRaises(TaskError):self.flow.act(operation,principal,'StableRequest',**args)
        self.assertEqual(len(self.journal.history(RUN)),count)

    def test_dispatch_does_not_automatically_accept_the_adapter_batch(self):
        self.prepare(); before=copy.deepcopy(self.flow.state['inventory'])
        result=self.flow.dispatch('Job01',HumanTeleportMock('AgentHuman',order=list(reversed(domain.ROLES))),OWNER,'Dispatch01')
        state=self.flow.state
        self.assertEqual(len(result['batch']),5);self.assertEqual(state['outbox']['Job01']['status'],'dispatched')
        self.assertEqual(state['jobs']['Job01']['phase'],'pickup_pending');self.assertEqual(state['inbox'],{})
        self.assertEqual(state['rack_placements']['SYN.Async.Rack01'],{'kind':'endpoint','endpoint_id':'LabA.S1'})
        self.flow.ingest(result['batch']);after=self.flow.state
        self.assertEqual(after['jobs']['Job01']['phase'],'completed')
        self.assertEqual(after['rack_placements']['SYN.Async.Rack01'],{'kind':'endpoint','endpoint_id':'LabB.S1'})
        self.assertEqual(after['inventory'],before);self.assertEqual(after['bookings'],{})
        self.assertIn('place:SYN.Site01|LabB|LabB.Handover|S1',after['resources'])
        self.assertNotIn('agent:AgentHuman',after['resources'])
        self.assertTrue(self.flow.report()['passed'])

    def test_second_request_or_new_worker_never_redispatches_a_committed_dispatch(self):
        self.prepare();first=HumanTeleportMock('AgentHuman');result=self.flow.dispatch('Job01',first,OWNER,'Dispatch01')
        adapter=Mock();replay=self.flow.dispatch('Job01',adapter,OWNER,'Dispatch01')
        self.assertTrue(replay['replayed']);self.assertIsNone(replay['batch']);adapter.submit.assert_not_called()
        with self.assertRaises(TaskError):self.flow.dispatch('Job01',adapter,OWNER,'DispatchAgain')
        adapter.submit.assert_not_called()
        self.flow.ingest(result['batch']);count=len(self.journal.history(RUN));self.flow.ingest(result['batch'])
        self.assertEqual(len(self.journal.history(RUN)),count)

    def test_human_and_robot_roundtrip_keep_materials_slots_quantities_and_null(self):
        self.prepare();inventory=copy.deepcopy(self.flow.state['inventory'])
        self.flow.ingest(self.flow.dispatch('Job01',HumanTeleportMock('AgentHuman'),OWNER,'HumanDispatch')['batch'])
        self.prepare(job='Return',target='LabA.S1',agent='AgentRobot')
        self.flow.ingest(self.flow.dispatch('Return',RobotTeleportMock('AgentRobot'),OWNER,'RobotDispatch')['batch'])
        state=self.flow.state;report=self.flow.report()
        self.assertEqual(state['inventory'],inventory);self.assertEqual(state['bookings'],{})
        self.assertEqual(state['rack_placements']['SYN.Async.Rack01'],{'kind':'endpoint','endpoint_id':'LabA.S1'})
        self.assertEqual(set(report['completed_jobs']),{'Job01','Return'})
        self.assertTrue(report['passed']);self.assertFalse(report['robot_motion_executed'])
        self.assertFalse(report['existing_workflow_integrated']);self.assertEqual(report['transport_time_s'],0)

    def test_disjoint_jobs_are_open_together_and_same_owner_cannot_bypass_subclaims(self):
        self.prepare();self.prepare(job='Job02',rack='SYN.Async.Rack02',target='LabB.S2',agent='AgentRobot')
        state=self.flow.state;self.assertEqual(set(state['outbox']),{'Job01','Job02'})
        self.assertFalse(set(state['jobs']['Job01']['claims'])&set(state['jobs']['Job02']['claims']))
        for job,rack,target,agent in [('SameCargo','SYN.Async.Rack01','LabB.S2','AgentRobot'),('SamePlace','SYN.Async.Rack02','LabB.S1','AgentRobot')]:
            self.act('request',job_id=job,rack_id=rack,target_endpoint=target,agent_id=agent)
            before=self.journal.history(RUN)
            with self.assertRaises(TaskError):self.act('reserve',job_id=job)
            self.assertEqual(self.journal.history(RUN),before)

    def test_two_connections_reject_a_stale_whole_root_proposal(self):
        self.act('admit')
        with Journal(self.path)as other:
            rival=AsyncTransport(other,RUN,self.flow.session);real=self.journal.append
            def race(*args,**kwargs):
                rival.act('request',OWNER,'RivalRequest',job_id='Rival',rack_id='SYN.Async.Rack02',target_endpoint='LabB.S2',agent_id='AgentRobot')
                return real(*args,**kwargs)
            with patch.object(self.journal,'append',side_effect=race):
                with self.assertRaisesRegex(TaskError,'changed'):
                    self.flow.act('request',OWNER,'LosingRequest',job_id='Loser',rack_id='SYN.Async.Rack01',target_endpoint='LabB.S1',agent_id='AgentHuman')
        state=self.flow.state;self.assertEqual(set(state['jobs']),{'Rival'});self.assertNotIn('LosingRequest',state['requests'])

    def test_parallel_owner_admission_one_wins_other_rolls_back_every_change(self):
        path=self.folder/'parallel.sqlite3';barrier=Barrier(2)
        def admit(identity):
            with Journal(path)as journal:
                flow=AsyncTransport.create(journal,identity);barrier.wait(timeout=15)
                try:flow.act('admit',OWNER,'Admission');return identity,True
                except TaskError:return identity,False
        with ThreadPoolExecutor(max_workers=2)as pool:
            results=list(pool.map(admit,['SYN.Async.One','SYN.Async.Two']))
        self.assertEqual(sum(ok for _,ok in results),1)
        with Journal(path)as journal:
            for identity,ok in results:
                state,revision=journal.state(identity);self.assertEqual(state['admitted'],ok)
                if not ok:
                    self.assertEqual(revision,1);self.assertEqual(state['inventory'],{});self.assertEqual(state['requests'],{})
            self.assertEqual(set(journal.owners().values()),{next(name for name,ok in results if ok)})

    def test_cancel_committed_after_dispatch_blocks_adapter_before_submit(self):
        self.prepare();real=self.flow._act;adapter=Mock();adapter.submit.return_value=[]
        def interleave(*args,**kwargs):
            result=real(*args,**kwargs)
            if args[0]=='mark_dispatched':
                with Journal(self.path)as journal:
                    other=AsyncTransport(journal,RUN,self.flow.session)
                    other.act('cancel',OWNER,'ConcurrentCancel',job_id='Job01',reason='cancel_before_submit')
            return result
        with patch.object(self.flow,'_act',side_effect=interleave):
            with self.assertRaisesRegex(TaskError,'superseded or held'):
                self.flow.dispatch('Job01',adapter,OWNER,'DispatchBeforeCancel')
        adapter.submit.assert_not_called();state=self.flow.state
        self.assertTrue(state['jobs']['Job01']['cancel_requested'])
        self.assertEqual(state['jobs']['Job01']['control'],'held')
        self.assertEqual(state['outbox']['Job01']['status'],'dispatched')
        self.assertIn('DispatchBeforeCancel',state['requests'])
        self.assertIn('agent:AgentHuman',state['resources'])
        self.assertEqual(state['rack_placements']['SYN.Async.Rack01'],{'kind':'endpoint','endpoint_id':'LabA.S1'})

    def test_late_conflict_of_another_job_same_rack_blocks_the_next_adapter_submit(self):
        self.prepare();batch=self.flow.dispatch('Job01',HumanTeleportMock('AgentHuman'),OWNER,'FirstDispatch')['batch']
        self.flow.ingest(batch)
        self.prepare(job='Return',target='LabA.S1',agent='AgentRobot')
        real=self.flow._act;adapter=Mock();adapter.submit.return_value=[]
        observation=copy.deepcopy(batch[1]['args']['observation'])
        observation.update(observation_id='HistoricalConflict',manifest_sha256='0'*64)
        def interleave(*args,**kwargs):
            result=real(*args,**kwargs)
            if args[0]=='mark_dispatched':
                with Journal(self.path)as journal:
                    other=AsyncTransport(journal,RUN,self.flow.session)
                    other.act('observe',batch[1]['principal'],'LateHistoricalMessage',job_id='Job01',observation=observation)
            return result
        with patch.object(self.flow,'_act',side_effect=interleave):
            with self.assertRaisesRegex(TaskError,'superseded or held'):
                self.flow.dispatch('Return',adapter,OWNER,'ReturnDispatch')
        adapter.submit.assert_not_called();state=self.flow.state
        self.assertEqual(state['jobs']['Job01']['control'],'held')
        self.assertEqual(state['outbox']['Return']['status'],'dispatched')
        self.assertEqual(state['rack_placements']['SYN.Async.Rack01'],{'kind':'endpoint','endpoint_id':'LabB.S1'})
        self.assertFalse(self.flow.report()['passed'])

    def test_failure_after_sql_event_insert_rolls_back_dispatch_and_never_calls_adapter(self):
        self.prepare();before=self.journal.history(RUN);holds=self.journal.owners();adapter=Mock();real=self.journal._event
        def fail(*args,**kwargs):real(*args,**kwargs);raise OSError('injected after event insert')
        with patch.object(self.journal,'_event',side_effect=fail):
            with self.assertRaises(OSError):self.flow.dispatch('Job01',adapter,OWNER,'FailedDispatch')
        adapter.submit.assert_not_called();self.assertEqual(self.journal.history(RUN),before);self.assertEqual(self.journal.owners(),holds)

    def test_failure_after_receipt_insert_rolls_back_inbox_artifact_request_and_custody(self):
        self.prepare();result=self.flow.dispatch('Job01',HumanTeleportMock('AgentHuman'),OWNER,'Dispatch')
        batch=[result['batch'][1]];checksum=digest(encoded(batch).encode());before=self.journal.history(RUN);real=self.journal._event
        def fail(*args,**kwargs):real(*args,**kwargs);raise OSError('injected inbox failure')
        with patch.object(self.journal,'_event',side_effect=fail):
            with self.assertRaises(OSError):self.flow.ingest(batch)
        self.assertEqual(self.journal.history(RUN),before)
        with self.assertRaises(TaskError):self.journal.artifact(checksum)
        self.assertEqual(self.flow.state['inbox'],{})
        self.flow.ingest(batch);self.assertEqual(len(self.flow.state['inbox']),1)

    def test_adapter_timeout_holds_uncertainty_and_keeps_resources(self):
        self.prepare();holds=self.journal.owners();adapter=Mock();adapter.submit.side_effect=TimeoutError('synthetic timeout')
        with self.assertRaises(TimeoutError):self.flow.dispatch('Job01',adapter,OWNER,'TimedOut')
        state=self.flow.state;self.assertEqual(state['jobs']['Job01']['control'],'held')
        self.assertEqual(state['jobs']['Job01']['receipts'],{});self.assertEqual(self.journal.owners(),holds)
        self.assertEqual(state['rack_placements']['SYN.Async.Rack01'],{'kind':'endpoint','endpoint_id':'LabA.S1'})
        self.assertFalse(self.flow.report()['passed'])

    def test_explicit_resume_fences_old_session_and_requires_reconciliation(self):
        self.prepare();old=self.flow;read=AsyncTransport.open(self.journal,RUN)
        with self.assertRaises(TaskError):read.act('cancel',OWNER,'ReadOnly',job_id='Job01',reason='test')
        with self.assertRaises(TaskError):AsyncTransport.open(self.journal,RUN,resume=True)
        fresh=AsyncTransport.open(self.journal,RUN,resume=True,principal=OWNER,request_id='ResumeOnce')
        self.assertEqual(fresh.state['assignment_epoch'],2);self.assertEqual(fresh.state['jobs']['Job01']['control'],'held')
        with self.assertRaises(TaskError):old.act('cancel',OWNER,'Stale',job_id='Job01',reason='test')
        count=len(self.journal.history(RUN));again=AsyncTransport.open(self.journal,RUN,resume=True,principal=OWNER,request_id='ResumeOnce')
        self.assertEqual(again.session,fresh.session);self.assertEqual(len(self.journal.history(RUN)),count)

    def test_hard_exit_after_dispatch_commit_survives_and_never_resends_after_restart(self):
        self.prepare();marker=self.folder/'adapter-was-called'
        script='''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[4])
from manual_tasks import Journal
from async_transport import AsyncTransport
with Journal(sys.argv[1])as journal:
 flow=AsyncTransport(journal,"SYN.Async.RuntimeTest",sys.argv[3]);real=flow._act
 def crash(*args,**kwargs):
  result=real(*args,**kwargs)
  if args[0]=="mark_dispatched":os._exit(77)
  return result
 flow._act=crash
 class Adapter:
  def submit(self,envelope):Path(sys.argv[2]).write_text("unexpected");return []
 flow.dispatch("Job01",Adapter(),"SYN.Async.Owner","CrashDispatch")
'''
        result=subprocess.run([sys.executable,'-B','-c',script,str(self.path),str(marker),self.flow.session,str(ROOT/'scripts')],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,77,result.stderr);self.assertFalse(marker.exists())
        prior=self.flow.state;self.assertEqual(prior['outbox']['Job01']['status'],'dispatched')
        holds=self.journal.owners();fresh=AsyncTransport.open(self.journal,RUN,resume=True,principal=OWNER,request_id='CrashResume')
        self.assertEqual(fresh.state['outbox']['Job01']['status'],'uncertain');self.assertEqual(self.journal.owners(),holds)
        adapter=Mock();replay=fresh.dispatch('Job01',adapter,OWNER,'CrashDispatch');self.assertTrue(replay['replayed'])
        with self.assertRaises(TaskError):fresh.dispatch('Job01',adapter,OWNER,'NewAttempt')
        adapter.submit.assert_not_called()
        observation=domain.observation_for(domain.envelope(prior,'Job01'),'pickup_release','LateOldReceipt')
        fresh.act('observe','SYN.LabA.Endpoint','LateOldMessage',job_id='Job01',observation=observation)
        self.assertEqual(fresh.state['inbox']['LateOldReceipt']['status'],'stale')
        self.assertEqual(fresh.state['rack_placements']['SYN.Async.Rack01'],{'kind':'endpoint','endpoint_id':'LabA.S1'})

    def test_late_conflict_cannot_relabel_historical_completion_as_current_pass(self):
        self.prepare();batch=self.flow.dispatch('Job01',HumanTeleportMock('AgentHuman'),OWNER,'Dispatch')['batch']
        self.flow.ingest(batch);self.assertTrue(self.flow.report()['passed'])
        observation=copy.deepcopy(batch[1]['args']['observation'])
        observation.update(observation_id='ConflictingLateEvidence',manifest_sha256='0'*64)
        self.flow.act('observe',batch[1]['principal'],'ConflictRequest',job_id='Job01',observation=observation)
        report=self.flow.report();self.assertFalse(report['passed'])
        self.assertEqual(report['completed_jobs'],[]);self.assertIn('Job01',report['unresolved_jobs'])
        self.assertIn('ConflictingLateEvidence',report['unresolved_inbox'])
        self.assertEqual(report['bookings'],{})

    def test_runtime_pins_drift_blocks_admission_without_editing_original_sources(self):
        source=self.folder/'source.json';source.write_bytes(domain.SOURCE.read_bytes())
        flow=AsyncTransport.create(self.journal,'SYN.Async.SourceDrift',source=source)
        before=self.journal.history(flow.run_id);source.write_bytes(source.read_bytes()+b'\n')
        with self.assertRaisesRegex(TaskError,'source changed'):flow.act('admit',OWNER,'Admission')
        self.assertEqual(self.journal.history(flow.run_id),before)

    def test_admission_cannot_bypass_existing_permanent_material_allocation(self):
        item={'material_id':'SYN.Async.Material01','vessel_id':'SYN.Async.Vessel01','declaration_sha256':'1'*64}
        state={'format':'solidcraftbot.material-workflow-state/1','definition':{'format':'solidcraftbot.material-workflow-definition/1','material_allocations':[item]},'resources':[]}
        self.journal.create('SYN.ExistingMaterial',state,immutable_definition=True,material_allocations=[item])
        before=self.journal.history(RUN)
        with self.assertRaisesRegex(TaskError,'permanently allocated'):self.act('admit')
        self.assertEqual(self.journal.history(RUN),before);self.assertFalse(self.flow.state['admitted'])
        self.assertEqual(self.journal.audit_material_allocations()['material:SYN.Async.Material01']['run_id'],'SYN.ExistingMaterial')

    def test_report_keeps_one_snapshot_during_another_connections_reservation_commit(self):
        self.act('admit')
        self.act('request',job_id='ReserveRacer',rack_id='SYN.Async.Rack01',target_endpoint='LabB.S1',agent_id='AgentHuman')
        ready,go=Event(),Event()
        def reserve():
            with Journal(self.path)as journal:
                flow=AsyncTransport(journal,RUN,self.flow.session)
                ready.set()
                if not go.wait(timeout=10):raise AssertionError('Report did not reach its resource read')
                return flow.act('reserve',OWNER,'ConcurrentReserve',job_id='ReserveRacer')
        original=self.journal.owners
        with ThreadPoolExecutor(max_workers=1)as pool:
            future=pool.submit(reserve)
            self.assertTrue(ready.wait(timeout=10))
            def while_writer_commits():
                go.set()
                try:future.result(timeout=.1)
                except FutureTimeout:pass
                return original()
            try:
                with patch.object(self.journal,'owners',side_effect=while_writer_commits):
                    report=self.flow.report()
            finally:go.set()
            future.result(timeout=10)
        self.assertEqual(report['jobs']['ReserveRacer']['phase'],'requested')
        self.assertEqual(self.flow.state['jobs']['ReserveRacer']['phase'],'reserved')
        self.assertNotIn('agent:AgentHuman',report['resources'])
        self.assertIn('agent:AgentHuman',self.flow.state['resources'])

    def test_report_detects_missing_global_resource_rows(self):
        self.act('admit');self.journal.connection.execute('DELETE FROM resources WHERE run_id=?',(RUN,));self.journal.connection.commit()
        with self.assertRaisesRegex(TaskError,'reservations'):self.flow.report()


if __name__=='__main__':unittest.main()
