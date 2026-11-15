"""Offline atomic-control checks; these do not claim a TLS/network run."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from extraction_analytics_demo import ACTOR
from extraction_analytics_sources import SOURCE
from extraction_analytics_workflow import ExtractionAnalyticsWorkflow
from extraction_analytics_sila2_control import MODE, NetworkExtractionAnalyticsWorkflow
from manual_tasks import Journal, TaskError, digest, encoded


class ExtractionAnalyticsSiLAControlTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='analytics-control-', dir=ROOT/'exports')
        self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name)/'workflows.sqlite3'); self.addCleanup(self.journal.close)
        self.run_id = 'SYN.Analytics.Control01'
        self.control = {'mode': MODE, 'server_uuid': 'test.server', 'source_files_sha256': {
            'scripts/extraction_analytics_sila2_control.py': digest((ROOT/'scripts/extraction_analytics_sila2_control.py').read_bytes())}}
        self.flow = self.create()

    def context(self, command='RunUntilDecision', request='run', boot='test.boot.1', principal='account.operator', **arguments):
        args = {'request_identifier':request, 'run_identifier':self.run_id, **arguments}
        return {'request_id':request, 'command':command, 'arguments':args,
            'fingerprint':digest(encoded({'command':command,'arguments':args}).encode()),
            'principal':principal, 'server_uuid':'test.server', 'boot_id':boot,
            'execution_uuid':'execution.'+request, 'clock':lambda: 123.0, 'transport':'in_process'}

    def create(self, context=None, identity=None):
        return NetworkExtractionAnalyticsWorkflow.create(self.journal, SOURCE, identity or self.run_id,
            control=self.control, command_context=context or self.context('CreateRun','create',family_identifier='dneasy'), actor_id=ACTOR)

    def command(self, request='run', guard=None):
        self.flow.command_context = self.context(request=request)
        self.flow.transition_guard = guard

    def test_create_receipt_is_in_same_first_root_commit_and_keeps_actor_separate(self):
        state = self.flow.state; trace = self.journal.history(self.run_id)
        self.assertEqual(len(trace),1)
        self.assertEqual(state['network']['commands']['create']['confirmation_event_sequence'],1)
        self.assertEqual(state['creation_receipt']['network_receipt']['principal'],'account.operator')
        self.assertEqual(state['responsible_person_id'],ACTOR)
        self.assertNotEqual(state['responsible_person_id'],state['creation_receipt']['network_receipt']['principal'])
        self.assertEqual(state['bookings'],{})

    def test_family_receipt_cannot_claim_another_chemistry(self):
        other = self.context('CreateRun','foreign',family_identifier='puregene')
        other['arguments']['run_identifier']=self.run_id+'.Bad'
        other['fingerprint']=digest(encoded({'command':'CreateRun','arguments':other['arguments']}).encode())
        with self.assertRaises(TaskError):self.create(other,self.run_id+'.Bad')
        with self.assertRaises(TaskError):self.journal.state(self.run_id+'.Bad')

    def test_first_effect_and_rejected_observation_have_correlated_durable_receipt(self):
        self.command('inventory')
        before=len(self.journal.history(self.run_id))
        self.flow.act('accept_inventory',ACTOR,observations=self.flow.inventory_observations())
        event=self.journal.history(self.run_id)[-1]
        self.assertEqual(event['payload']['network_receipt']['request_id'],'inventory')
        self.assertEqual(event['state']['network']['commands']['inventory']['confirmation_event_sequence'],before+1)
        self.command('bad-workspace')
        with self.assertRaises(TaskError):self.flow.act('workspace_clear',ACTOR,confirmed=False)
        event=self.journal.history(self.run_id)[-1]
        self.assertEqual(event['kind'],'observation_rejected')
        self.assertEqual(event['state']['network']['commands']['bad-workspace']['status'],'accepted')
        self.assertEqual(event['payload']['network_receipt']['principal'],'account.operator')

    def test_plain_local_adapter_cannot_write_resume_or_close_network_root(self):
        before=self.journal.history(self.run_id)
        local=ExtractionAnalyticsWorkflow(self.journal,self.run_id,self.flow.session)
        for action in (lambda:local.act('cancel',ACTOR,reason='forbidden'),lambda:local.close(),
                       lambda:ExtractionAnalyticsWorkflow.open(self.journal,self.run_id,resume=True)):
            with self.assertRaises(TaskError):action()
        self.assertEqual(self.journal.history(self.run_id),before)
        self.assertFalse(local.report()['passed'])

    def test_guard_failure_prevents_first_receipt_and_effect(self):
        def fail():raise PermissionError('Lease expired')
        self.command('expired',fail);before=self.journal.history(self.run_id)
        with self.assertRaises(PermissionError):self.flow.act('accept_inventory',ACTOR,observations=self.flow.inventory_observations())
        self.assertEqual(self.journal.history(self.run_id),before)
        self.assertNotIn('expired',self.flow.state['network']['commands'])

    def test_storage_failure_keeps_receipt_and_effect_atomic(self):
        self.command('storage');before=self.journal.history(self.run_id)
        with patch.object(self.journal,'_event',side_effect=TaskError('Injected persistence failure')):
            with self.assertRaises(TaskError):self.flow.act('accept_inventory',ACTOR,observations=self.flow.inventory_observations())
        self.assertEqual(self.journal.history(self.run_id),before)
        self.assertNotIn('storage',self.flow.state['network']['commands'])

    def test_payload_cannot_forge_system_network_receipt(self):
        self.command('controller')
        self.flow.control_event('controller_observation',lambda state:None,{
            'network_receipt':{'principal':'forged'},'actor_id':'forged','evidence':'hardware','detail':'preserved'})
        payload=self.journal.history(self.run_id)[-1]['payload']
        self.assertEqual(payload['network_receipt']['principal'],'account.operator')
        self.assertEqual(payload['evidence'],'network_receipt')
        self.assertEqual(payload['detail'],'preserved')

    def test_completed_request_cannot_be_redispatched_by_engine(self):
        self.command('done');self.flow.control_event('observation',lambda state:None)
        self.flow.finish_command({'outcome':'completed'})
        before=self.journal.history(self.run_id)
        with self.assertRaises(TaskError):self.flow.act('accept_inventory',ACTOR,observations=self.flow.inventory_observations())
        self.assertEqual(self.journal.history(self.run_id),before)

    def test_atomic_resume_fences_old_session_and_marks_old_receipts_uncertain(self):
        self.command('open');self.flow.control_event('observation',lambda state:None)
        oldsession=self.flow.session
        context=self.context('ResumeRun','resume',boot='test.boot.2',resume=True)
        resumed=NetworkExtractionAnalyticsWorkflow.open(self.journal,self.run_id,resume=True,
            control=self.control,command_context=context)
        self.assertNotEqual(resumed.session,oldsession)
        self.assertEqual(resumed.state['network']['commands']['open']['status'],'uncertain')
        self.assertEqual(resumed.state['network']['commands']['resume']['status'],'accepted')
        event=self.journal.history(self.run_id)[-1]
        self.assertEqual(event['payload']['network_receipt']['boot_id'],'test.boot.2')
        before=self.journal.history(self.run_id)
        with self.assertRaises(TaskError):self.flow.control_event('stale',lambda state:None)
        self.assertEqual(self.journal.history(self.run_id),before)

    def test_resume_storage_failure_does_not_rotate_session_or_receipt(self):
        before=self.journal.history(self.run_id)
        context=self.context('ResumeRun','resume',boot='test.boot.2',resume=True)
        with patch.object(self.journal,'_event',side_effect=TaskError('Injected persistence failure')):
            with self.assertRaises(TaskError):NetworkExtractionAnalyticsWorkflow.open(self.journal,self.run_id,resume=True,
                control=self.control,command_context=context)
        self.assertEqual(self.journal.history(self.run_id),before)

    def test_command_context_fingerprint_and_source_control_are_checked(self):
        self.command('badfingerprint');self.flow.command_context['fingerprint']='0'*64
        before=self.journal.history(self.run_id)
        with self.assertRaises(TaskError):self.flow.act('accept_inventory',ACTOR,observations=self.flow.inventory_observations())
        self.assertEqual(self.journal.history(self.run_id),before)
        self.command('badcontrol');self.flow.command_context['server_uuid']='another.server'
        with self.assertRaises(TaskError):self.flow.act('accept_inventory',ACTOR,observations=self.flow.inventory_observations())
        self.assertEqual(self.journal.history(self.run_id),before)


if __name__=='__main__':unittest.main()
