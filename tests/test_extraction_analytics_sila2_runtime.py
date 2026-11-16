"""Offline service-coordinator cases; actual TLS is tested separately."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from dna_sila2_runtime import DNARuntime
from extraction_analytics_sila2_runtime import ExtractionAnalyticsRuntime, RECONCILIATION
from extraction_analytics_demo import ACTOR
from extraction_analytics_sila2_control import NetworkExtractionAnalyticsWorkflow
from extraction_demo import perform_phase, phase_observations, actual_inputs
from manual_tasks import Journal, TaskError, digest, encoded


class ExtractionAnalyticsSiLARuntimeTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'exports').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='analytics-runtime-',dir=ROOT/'exports')
        self.addCleanup(self.temp.cleanup)
        self.host=DNARuntime(Path(self.temp.name));self.addCleanup(self.host.close)
        self.runtime=ExtractionAnalyticsRuntime(self.host)
        self.run='SYN.Analytics.Runtime01';self.serial=0

    def command(self,name,request=None,**data):
        self.serial+=1
        return self.runtime.command(name,{'request_identifier':request or 'request.%d'%self.serial,
            'run_identifier':self.run,**data},'account.operator')

    def create(self,family='dneasy'):return self.command('CreateRun',family_identifier=family)

    def state(self):
        with Journal(self.runtime.journal_path) as journal:return journal.get_current(self.run)[0]

    def observations(self,state=None):
        state=self.state() if state is None else state
        return [{'vessel_id':identity,'material_ids':[key for key,m in state['inventory']['materials'].items() if m['vessel_id']==identity],
            'location':copy.deepcopy(vessel['location'])} for identity,vessel in state['inventory']['vessels'].items()]

    def document(self,**data):
        return {'format':RECONCILIATION,'reason':'Explicit synthetic test observation',
            'observations':self.observations(),'workspace_clear':True,**data}

    def pending_phase(self):
        """Leave a real persisted extraction intent, not an invented state."""
        self.runtime.pause_after='phase_intent'
        results=[]
        thread=threading.Thread(target=lambda:results.append(self.command('RunUntilDecision',request='paused')))
        thread.start()
        for _ in range(500):
            state=self.state();pending=state['process']['phase_pending']
            if pending and pending['intent_id'] in state['bookings']:break
            time.sleep(.01)
        else:self.fail('No persisted phase intent')
        execution=self.state()['network']['commands']['paused']['execution_uuid']
        replay=self.command('RunUntilDecision',request='paused')
        self.assertEqual(replay['outcome'],'accepted')
        self.runtime.cancel_execution(execution,principal='account.operator')
        thread.join(30);self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]['outcome'],'interrupted')
        self.runtime.pause_after=None

    def test_same_journal_features_filter_roots_and_reject_cross_feature_commands(self):
        self.host.command('CreateRun',{'request_identifier':'legacy-create','run_identifier':'SYN.Legacy01'},'account.operator')
        self.create()
        self.assertEqual(self.runtime.journal_path,self.host.journal_path)
        self.assertIs(self.runtime._mutex,self.host._mutex)
        self.assertEqual(self.host.status()['run_ids'],['SYN.Legacy01'])
        self.assertEqual(self.runtime.status()['run_ids'],[self.run])
        self.assertEqual(set(self.host.report()['reports']),{'SYN.Legacy01'})
        self.assertEqual(set(self.runtime.report()['reports']),{self.run})
        with self.assertRaises(TaskError):self.host.command('CancelRun',{
            'request_identifier':'wrong','run_identifier':self.run,'reason':'cross feature'},'account.operator')
        with self.assertRaises(TaskError):self.runtime.command('CancelRun',{
            'request_identifier':'wrong','run_identifier':'SYN.Legacy01','reason':'cross feature'},'account.operator')

    def test_request_replay_conflict_and_principal_binding_do_not_add_effects(self):
        result=self.command('CreateRun',request='create',family_identifier='dneasy')
        with Journal(self.runtime.journal_path) as j:before=j.history(self.run)
        self.assertEqual(result,self.command('CreateRun',request='create',family_identifier='dneasy'))
        with self.assertRaises(TaskError):self.command('CreateRun',request='create',family_identifier='puregene')
        with self.assertRaises(TaskError):self.runtime.command('CreateRun',{
            'request_identifier':'create','run_identifier':self.run,'family_identifier':'dneasy'},'other.principal')
        with Journal(self.runtime.journal_path) as j:self.assertEqual(j.history(self.run),before)

    def test_both_families_complete_with_one_ledger_and_compact_historical_trace(self):
        for family,amount in [('dneasy',195.5),('puregene',95.5)]:
            with self.subTest(family=family):
                self.run='SYN.Analytics.'+family
                run_request='run.'+family
                self.create(family)
                if family=='dneasy':
                    # Inject precisely the crash window after terminal domain
                    # release and before its network completion receipt.
                    with patch.object(NetworkExtractionAnalyticsWorkflow,'finish_command',side_effect=OSError('Injected completion write loss')):
                        with self.assertRaises(OSError):self.command('RunUntilDecision',request=run_request)
                    before=self.state()
                    self.assertEqual(before['status'],'completed')
                    self.assertEqual(before['network']['commands'][run_request]['status'],'accepted')
                    self.command('ResumeRun',resume=True)
                    after=self.state()
                    self.assertEqual(after['network']['commands'][run_request]['status'],'uncertain')
                    for key in ('inventory','bookings','resources','status'):
                        self.assertEqual(after[key],before[key])
                    self.assertIsNone(after['session'])
                    replay_outcome='uncertain'
                else:
                    self.command('RunUntilDecision',request=run_request);replay_outcome='completed'
                report=self.runtime.report(self.run)
                self.assertTrue(report['passed']);self.assertEqual(report['resources'],[])
                product=next(key for key,m in report['inventory']['materials'].items() if m['kind']=='product')
                self.assertEqual(report['remaining'][product]['value'],amount)
                self.assertEqual(report['inventory']['materials'][product]['disposition'],'retained')
                self.assertFalse(report['network_executed']);self.assertFalse(report['hardware_executed'])
                self.assertFalse(report['fragment_size_qualified']);self.assertFalse(report['sop_qualified'])
                self.assertTrue(all(set(event)=={'sequence','kind','sha256','previous_sha256','time_unix_s'} for event in report['trace']))
                self.assertEqual(report['wire_projection']['trace'],'metadata_only')
                before=self.state()['bookings']
                self.assertEqual(self.command('RunUntilDecision',request=run_request)['outcome'],replay_outcome)
                self.assertEqual(self.state()['bookings'],before)

    def test_resume_and_unknown_phase_keep_holds_until_explicit_resolution(self):
        self.create();self.pending_phase()
        previous=self.state();intent=previous['process']['phase_pending']['intent_id']
        self.command('ResumeRun',resume=True)
        doc=self.document(extraction={'intent_id':intent,'outcome':'unknown','reason':'Explicit unknown fixture effect'})
        self.command('ReconcileRun',observation_json=json.dumps(doc))
        state=self.state();self.assertEqual(state['bookings'][intent]['outcome'],'unknown')
        self.assertTrue(state['resources']);self.assertTrue(state['recovery_required'])
        with self.assertRaises(TaskError):self.command('RunUntilDecision')
        self.command('CancelRun',reason='Explicit controlled abort')
        doc=self.document(extraction={'intent_id':intent,'outcome':'not_performed','reason':'Explicit fixture nonperformance'})
        self.command('ReconcileRun',observation_json=json.dumps(doc))
        state=self.state()
        rows=[{'material_id':key,'disposition':'retained','reason':'Retain explicit remaining synthetic material'}
              for key,m in state['inventory']['materials'].items() if m['disposition'] not in {'consumed','discarded'}]
        doc=self.document(dispositions=rows)
        self.command('FinishCancel',observation_json=json.dumps(doc))
        self.assertEqual(self.state()['status'],'cancelled');self.assertEqual(self.state()['resources'],[])

    def test_reconciliation_rejects_duplicates_depth_nonfinite_and_foreign_fields_without_effect(self):
        self.create()
        with Journal(self.runtime.journal_path) as j:before=j.history(self.run)
        bad=['[]','{"format":"x","format":"y"}', '['*40+'0'+']'*40,
             json.dumps(self.document(extra=True)),json.dumps(self.document()).replace('true','1e999'),
             '['*1200+'0'+']'*1200,'{"value":NaN}']
        for raw in bad:
            with self.subTest(raw=raw[:40]),self.assertRaises(TaskError):self.command('ReconcileRun',observation_json=raw)
        with Journal(self.runtime.journal_path) as j:self.assertEqual(j.history(self.run),before)

    def test_resume_before_initial_inventory_can_reconcile_created_root_without_reseeding(self):
        self.create();before=self.state()['inventory'];self.command('ResumeRun',resume=True)
        self.command('ReconcileRun',observation_json=json.dumps(self.document()))
        state=self.state();self.assertEqual(state['status'],'ready');self.assertIsNone(state['recovery_required'])
        self.assertEqual(state['inventory']['materials'],before['materials'])
        self.assertEqual(state['bookings'],{})

    def test_tapestation_cancel_requires_explicit_stop_retrieval_and_accounted_identities(self):
        self.create();self.runtime.pause_after='tapestation_loaded';results=[]
        thread=threading.Thread(target=lambda:results.append(self.command('RunUntilDecision',request='ts-run')))
        thread.start()
        for _ in range(9000):
            if self.state()['process']['qc']['loaded']:break
            time.sleep(.2)
        else:self.fail('No persisted TapeStation loading')
        execution=self.state()['network']['commands']['ts-run']['execution_uuid']
        self.runtime.cancel_execution(execution,principal='account.operator');thread.join(30)
        self.assertFalse(thread.is_alive());self.runtime.pause_after=None
        self.command('ResumeRun',resume=True)
        self.assertTrue(self.state()['network']['tapestation_recovery_required'])
        self.command('CancelRun',reason='Explicit fixture abort')
        state=self.state();rows=[];observations=self.observations(state)
        discarded=set()
        for key,m in state['inventory']['materials'].items():
            if m['disposition'] in {'consumed','discarded'}:continue
            desired='retained' if m['kind'] in {'product','reagent'} else 'discarded'
            rows.append({'material_id':key,'disposition':desired,'reason':'Explicit fixture material disposition'})
            if desired=='discarded':discarded.add(key)
        for observed in observations:observed['material_ids']=[k for k in observed['material_ids'] if k not in discarded]
        doc=self.document(dispositions=rows,observations=observations)
        before=self.state()['bookings']
        with self.assertRaises(TaskError):self.command('FinishCancel',observation_json=json.dumps(doc))
        self.assertEqual(self.state()['bookings'],before);self.assertTrue(self.state()['resources'])
        with Journal(self.runtime.journal_path) as j:
            flow=NetworkExtractionAnalyticsWorkflow(j,self.run,self.runtime._sessions[self.run])
            expected=flow.expected_tapestation_abort()
        doc['tapestation_abort']={'reason':'Explicit fixture stopped and retrieved observation','observations':{
            **expected,'instrument_stopped':True,'sample_retrieved':True,'ladder_retrieved':True,
            'materials_accounted':True,'identities_confirmed':True}}
        good=copy.deepcopy(doc)
        doc['tapestation_abort']['observations']['instrument_stopped']=1
        with self.assertRaises(TaskError):self.command('FinishCancel',observation_json=json.dumps(doc))
        doc=copy.deepcopy(good)
        doc['tapestation_abort']['observations']['sample_material_id']=1
        with self.assertRaises(TaskError):self.command('FinishCancel',observation_json=json.dumps(doc))
        doc=good
        self.command('FinishCancel',observation_json=json.dumps(doc))
        self.assertEqual(self.state()['status'],'cancelled');self.assertFalse(self.state()['resources'])

    def test_abnormally_performed_elution_preserves_quarantined_product_on_cancel(self):
        self.create()
        args={'request_identifier':'fixture-phases','run_identifier':self.run}
        context={'request_id':'fixture-phases','fingerprint':digest(encoded({'command':'RunUntilDecision','arguments':args}).encode()),
            'command':'RunUntilDecision','arguments':args,'principal':'account.operator','server_uuid':self.runtime.server_uuid,
            'boot_id':self.runtime.boot_id,'execution_uuid':'fixture-elution-execution','clock':self.runtime.clock,'transport':'in_process'}
        with Journal(self.runtime.journal_path) as journal:
            flow=NetworkExtractionAnalyticsWorkflow(journal,self.run,self.runtime._sessions[self.run],command_context=context)
            flow.act('accept_inventory',ACTOR,observations=flow.inventory_observations())
            flow.act('workspace_clear',ACTOR,confirmed=True);flow.act('claim',ACTOR)
            execution=flow.state['definition']['execution'];sample=next(iter(execution['samples']))
            for step in execution['steps'][:-1]:perform_phase(flow,sample,step,actor_id=ACTOR)
            step=execution['steps'][-1];self.assertEqual(step['id'],'spin_elute')
            intent=self.run+'.Phase.'+step['id']
            flow.act('begin_phase',ACTOR,sample_id=sample,phase_id=step['id'],intent_id=intent)
            flow.act('advance_time',ACTOR,seconds=step['parameters']['duration_s'])
            inputs=actual_inputs(flow.state,intent);outputs=step['fixture_actual_outputs']
            observations=phase_observations(step);observations['spin_complete']=False
            flow.act('mark_effect_unknown',ACTOR,intent_id=intent,reason='Explicit fixture uncertainty after incomplete elution spin')
            resolution={'intent_id':intent,'outcome':'performed_abnormal','actual_inputs':inputs,'actual_outputs':outputs,
                'observations':observations,'reason':'Observed product but incomplete synthetic spin; quarantine it'}
            proposal=copy.deepcopy(flow.state)
            flow._resolve_effect(proposal,ACTOR,**resolution)
        self.command('ResumeRun',resume=True)
        doc=self.document(extraction=resolution,observations=self.observations(proposal))
        self.command('ReconcileRun',observation_json=json.dumps(doc))
        state=self.state();product=state['definition']['execution']['analytics']['product_material_id']
        self.assertEqual(state['inventory']['materials'][product]['disposition'],'quarantined')
        self.assertIs(state['process']['operations'][intent]['confirmation']['observations']['spin_complete'],False)
        with self.assertRaises(TaskError):self.command('RunUntilDecision')
        self.command('CancelRun',reason='Controlled abort preserves known-bad product')
        state=self.state();rows=[];discarded=set()
        for identity,material in state['inventory']['materials'].items():
            if material['disposition'] in {'discarded','consumed'}:continue
            desired=('quarantined' if material['disposition']=='quarantined' else
                'retained' if material['kind'] in {'reagent','product'} else 'discarded')
            rows.append({'material_id':identity,'disposition':desired,'reason':'Explicit fixture disposition after abnormal spin'})
            if desired=='discarded':discarded.add(identity)
        observed=self.observations(state)
        for item in observed:item['material_ids']=[i for i in item['material_ids'] if i not in discarded]
        self.command('FinishCancel',observation_json=json.dumps(self.document(dispositions=rows,observations=observed)))
        state=self.state();spec=state['definition']['execution']['analytics']
        self.assertEqual(state['status'],'cancelled');self.assertEqual(state['resources'],[])
        self.assertEqual(state['inventory']['materials'][product]['disposition'],'quarantined')
        self.assertEqual(state['inventory']['materials'][product]['vessel_id'],spec['product_vessel_id'])
        self.assertEqual(state['inventory']['vessels'][spec['product_vessel_id']]['location'],spec['product_home'])
        self.assertFalse(self.runtime.report(self.run)['passed'])


if __name__=='__main__':unittest.main()
