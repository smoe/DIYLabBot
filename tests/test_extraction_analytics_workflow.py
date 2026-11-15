"""One typed balance across extraction and three independent QC methods."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import material_ledger as ledger
from manual_tasks import Journal,TaskError
from extraction_analytics_workflow import ExtractionAnalyticsWorkflow
from extraction_analytics_demo import run_demo,SyntheticExtractionBackend,ACTOR
from extraction_demo import REASON,run_tapestation
from dneasy_extraction_workflow import DNeasyWorkflow
from puregene_extraction_workflow import PuregeneWorkflow
from qubit_manual import next_preparation,calibration_binding

RUN='SYN.ExtractionQC.Unit'


class ExtractionAnalyticsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'exports').mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='analytics-runtime-',dir=ROOT/'exports')
        cls.addClassCleanup(cls.temp.cleanup);cls.folder=Path(cls.temp.name)
        cls.prefix=cls.folder/'extracted.sqlite3'
        with Journal(cls.prefix) as j:run_demo(j,run_id=RUN,pause_after='extracted')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='case-',dir=self.folder)
        self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'workflow.sqlite3'
        shutil.copyfile(self.prefix,self.path)
        self.journal=Journal(self.path);self.addCleanup(self.journal.close)
        self.flow=ExtractionAnalyticsWorkflow.open(self.journal,RUN)
        self.addCleanup(self.flow.close)
        self.flow.act('reconcile',ACTOR,observations=self.flow.inventory_observations(),workspace_clear=True)
        self.backend=SyntheticExtractionBackend(actor_id=ACTOR)

    def spec(self):return self.flow.state['definition']['execution']['analytics']
    def remaining(self):return ledger.remaining(self.flow.state,self.spec()['product_material_id'])['value']
    def start(self,device):
        self.flow.act('start_device',ACTOR,device=device);return self.flow.device(device)
    def complete_nd(self):
        self.start('nanodrop');self.backend.run_device(self.flow,'nanodrop')
    def nd_intent(self):
        handle=self.start('nanodrop');self.backend._claim(handle)
        handle.act('blank',ACTOR,reference_id='SYN.UnitBlank',cleaned=True)
        sample_id=self.spec()['sample_id'];self.backend._take(handle,sample_id)
        handle.act('begin_measurement',ACTOR,sample_id=sample_id,
                   measurement_id=handle.state['planned_measurements'][sample_id])
        return handle
    def confirm_nd(self,handle):
        pending=handle.state['pending_measurement']
        return handle.act('confirm_measurement',ACTOR,intent_id=pending['intent_id'],
            observed_sample_id=self.spec()['sample_id'],volume_ul=1.5,cleaned=True)
    def reconcile_device(self,device,resolution=None,valid=True):
        self.flow.act('resolve_device',ACTOR,device=device,pending_resolution=resolution,device_valid=valid,reason=REASON)
        self.flow.act('reconcile',ACTOR,observations=self.flow.inventory_observations(),workspace_clear=True)

    def test_new_engine_rejects_standalone_adapters_and_has_only_one_material_inventory(self):
        state=self.flow.state;spec=self.spec()
        with self.assertRaises(TaskError):DNeasyWorkflow(self.journal,RUN,None)
        with self.assertRaises(TaskError):PuregeneWorkflow(self.journal,RUN,None)
        self.assertEqual(state['analytics'],{'active_device':None,'stages':{}})
        self.assertEqual(set(state['inventory']),{'materials','vessels'})
        self.assertTrue(set(spec['qubit_tubes'].values())<=set(state['inventory']['vessels']))
        self.assertEqual(self.remaining(),200)

    def test_nd_intent_and_confirmation_survive_atomic_root_replacement(self):
        handle=self.nd_intent();pending=copy.deepcopy(handle.state['pending_measurement'])
        state=self.flow.state;binding=state['analytics']['stages']['nanodrop']['bindings'][pending['intent_id']]
        self.assertEqual(binding['inputs'][0]['material_id'],self.spec()['product_material_id'])
        self.assertEqual(state['bookings'][pending['intent_id']]['outcome'],'intent')
        self.assertIsNone(ledger.remaining(state,self.spec()['product_material_id'])['value'])
        self.confirm_nd(handle);state=self.flow.state
        self.assertIsNone(handle.state['pending_measurement'])
        self.assertIn(pending['measurement_id'],handle.state['measurements'])
        self.assertEqual(self.remaining(),198.5)
        before=state['bookings'][pending['intent_id']]
        with self.assertRaises(TaskError):
            handle.act('confirm_measurement',ACTOR,intent_id=pending['intent_id'],
                       observed_sample_id=self.spec()['sample_id'],volume_ul=1.5,cleaned=True)
        self.assertEqual(self.flow.state['bookings'][pending['intent_id']],before)
        self.assertEqual(self.remaining(),198.5)

    def test_dneasy_three_qc_methods_keep_product_and_debit_once(self):
        self.complete_nd();self.start('qubit');self.backend.run_device(self.flow,'qubit')
        self.assertEqual(self.remaining(),196.5)
        state=self.flow.state;context=state['analytics']['stages']['qubit']
        self.assertEqual(context['local']['calibration']['status'],'approved')
        self.assertEqual(len(context['derived']),3)
        ws=self.spec()['reagent_bindings']['working_solution']
        standard_ids=set(self.spec()['reagent_bindings']['standards'].values())
        working_doses=[i['quantity']['value'] for b in state['bookings'].values() for i in b['actual_inputs'] if i['material_id']==ws]
        self.assertEqual(sorted(working_doses),[190,190,198])
        for identity in standard_ids:
            self.assertEqual([i['quantity']['value'] for b in state['bookings'].values() for i in b['actual_inputs'] if i['material_id']==identity],[10])
        for meta in context['derived'].values():
            material=state['inventory']['materials'][meta['material_id']]
            self.assertEqual(material['disposition'],'discarded')
            self.assertIn(ws,material['parents'])
            prep=context['local']['preparations'][meta['preparation_id']]
            if prep['kind']=='standard':
                self.assertNotIn(self.spec()['product_material_id'],material['parents'])
                self.assertTrue(standard_ids & set(material['parents']))
            else:self.assertIn(self.spec()['product_material_id'],material['parents'])
        r=run_tapestation(self.flow,self.flow.state['definition'],actor_id=ACTOR)
        self.assertTrue(r['passed']);self.assertEqual(self.remaining(),195.5)
        self.assertEqual(r['inventory']['materials'][self.spec()['product_material_id']]['disposition'],'retained')
        self.assertFalse(r['hardware_executed']);self.assertFalse(r['fragment_size_qualified'])
        self.assertEqual(r['resources'],[])

    def test_puregene_full_composition_keeps_its_own_product_and_95_5_ul(self):
        other=Path(self.temp.name)/'puregene.sqlite3'
        with Journal(other) as j:
            r=run_demo(j,run_id='SYN.ExtractionQC.PG',source=ROOT/'model/extraction-analytics.puregene.json')
            self.assertTrue(r['passed']);self.assertFalse(r['biochemical_protocol_executed'])
            state=j.state('SYN.ExtractionQC.PG')[0]
            spec=state['definition']['execution']['analytics']
            self.assertEqual(spec['family'],'puregene')
            self.assertEqual(ledger.remaining(state,spec['product_material_id'])['value'],95.5)
            self.assertEqual(state['inventory']['materials'][spec['product_material_id']]['vessel_id'],spec['product_vessel_id'])

    def test_resume_keeps_nd_intent_and_requires_device_plus_inventory_reconciliation(self):
        handle=self.nd_intent();pending=copy.deepcopy(handle.state['pending_measurement'])
        before=copy.deepcopy(self.flow.state['bookings']);self.flow.close()
        self.flow=ExtractionAnalyticsWorkflow.open(self.journal,RUN,resume=True)
        self.assertEqual(self.flow.state['bookings'],before)
        history=self.journal.history(RUN)
        with self.assertRaises(TaskError):self.flow.act('resolve_device',ACTOR,device='nanodrop',pending_resolution=[],device_valid=True,reason=REASON)
        self.assertEqual(self.journal.history(RUN),history)
        with self.assertRaises(TaskError):self.flow.act('reconcile',ACTOR,observations=self.flow.inventory_observations(),workspace_clear=True)
        self.reconcile_device('nanodrop',{'outcome':'performed','intent_id':pending['intent_id'],
            'observed_sample_id':self.spec()['sample_id'],'volume_ul':1.5,'cleaned':True})
        self.assertEqual(self.remaining(),198.5)
        self.assertIsNone(self.flow.device('nanodrop').state['pending_measurement'])

    def test_wrong_nd_sample_holds_and_preserves_unresolved_material_intent(self):
        handle=self.nd_intent();pending=copy.deepcopy(handle.state['pending_measurement'])
        with self.assertRaises(TaskError):handle.act('confirm_measurement',ACTOR,intent_id=pending['intent_id'],observed_sample_id='foreign',volume_ul=1.5,cleaned=True)
        self.assertEqual(self.flow.state['bookings'][pending['intent_id']]['outcome'],'intent')
        self.assertTrue(self.flow.state['recovery_required'])
        self.assertTrue(self.flow.state['process']['deviations'])

    def test_changed_nd_source_revision_blocks_confirmation(self):
        handle=self.nd_intent();pending=copy.deepcopy(handle.state['pending_measurement'])
        state,rev=self.journal.state(RUN)
        state['inventory']['vessels'][self.spec()['product_vessel_id']]['content_revision']+=1
        self.journal.append(RUN,rev,'test_external_content_change',{},state)
        with self.assertRaises(TaskError):self.confirm_nd(handle)
        self.assertEqual(self.flow.state['bookings'][pending['intent_id']]['outcome'],'intent')

    def test_journal_failure_does_not_leave_partial_measurement_or_ledger_intent(self):
        handle=self.start('nanodrop');self.backend._claim(handle)
        handle.act('blank',ACTOR,reference_id='SYN.UnitBlank',cleaned=True)
        sample=self.spec()['sample_id'];self.backend._take(handle,sample)
        before=self.flow.state
        with patch.object(self.journal,'append',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):handle.act('begin_measurement',ACTOR,sample_id=sample,measurement_id=handle.state['planned_measurements'][sample])
        self.assertEqual(self.flow.state,before)

    def test_tapestation_and_qubit_cannot_start_early(self):
        with self.assertRaises(TaskError):self.start('qubit')
        with self.assertRaises(TaskError):self.flow.act('begin_qc_preparation',ACTOR,role='sample',intent_id='early')
        with self.assertRaises(TaskError):self.flow.act('release',ACTOR,workspace_clear=True)
        self.assertEqual(self.remaining(),200)

    def test_unknown_nd_flag_and_out_of_range_values_do_not_pass_review(self):
        handle=self.nd_intent();self.confirm_nd(handle);self.backend._place(handle,self.spec()['sample_id'])
        # Preserve original data but require manual review to reject the unknown flag.
        from extraction_analytics_demo import _DevicePort
        high=SyntheticExtractionBackend({'nanodrop':1000000000,'qubit':48},actor_id=ACTOR)
        raw=high.nanodrop_report(_DevicePort(self.flow),'nanodrop')
        handle.import_content(raw,ACTOR)
        self.assertTrue(handle.state['results'])
        with self.assertRaises(TaskError):handle.act('review_results',ACTOR,decision='accepted',reason=REASON)
        self.assertTrue(self.flow.state['recovery_required'])
        self.assertEqual(self.remaining(),198.5)

    def test_unknown_nanodrop_warning_is_preserved_and_blocks_normal_review(self):
        handle=self.nd_intent();self.confirm_nd(handle);self.backend._place(handle,self.spec()['sample_id'])
        from extraction_analytics_demo import _DevicePort
        raw=self.backend.nanodrop_report(_DevicePort(self.flow),'nanodrop').replace(b',50,\r\n',b',50,UnknownWarning\r\n')
        handle.import_content(raw,ACTOR)
        self.assertTrue(any(any(r['instrument_messages'].values()) for r in handle.state['results'].values()))
        with self.assertRaises(TaskError):handle.act('review_results',ACTOR,decision='accepted',reason=REASON)
        self.assertTrue(self.flow.state['recovery_required'])

    def test_device_deadline_holds_and_needs_explicit_validity_observation(self):
        handle=self.start('nanodrop');self.backend._claim(handle)
        self.flow.act('advance_time',ACTOR,seconds=handle.state['definition']['profile']['parameters']['task_deadline_s'])
        self.assertEqual(self.flow.state['recovery_required'],'analytics_device_deadline_exceeded')
        with self.assertRaises(TaskError):handle.act('blank',ACTOR,reference_id='late',cleaned=True)
        self.reconcile_device('nanodrop')
        handle.act('blank',ACTOR,reference_id='after_explicit_reconciliation',cleaned=True)

    def test_qubit_calibration_rejects_wrong_assay_or_lot_binding(self):
        self.complete_nd();handle=self.start('qubit');self.backend._claim(handle)
        prepared=[]
        for standard in handle.state['definition']['protocol']['assay']['standards']:
            prepared.append(self.backend._begin_preparation(handle,'standard',standard['id']))
            self.backend._confirm_preparation(handle)
        self.flow.act('advance_time',ACTOR,seconds=handle.state['definition']['profile']['parameters']['incubation_min_s'])
        for identity in prepared:self.backend._measure_qubit(handle,identity)
        mapping={p['target_id']:p['measurement_id'] for p in handle.state['preparations'].values()}
        wrong=calibration_binding(handle.state);wrong['kit_lot']='SYN.ForeignLot'
        with self.assertRaises(TaskError):handle.act('approve_calibration',ACTOR,binding=wrong,standard_measurements=mapping,confirmed=True,reason=REASON)
        self.assertEqual(handle.state['calibration']['status'],'pending')
        self.assertEqual(self.remaining(),198.5)

    def test_qubit_standard_warning_survives_import_and_blocks_acceptance(self):
        import csv,io
        class FlaggedBackend(SyntheticExtractionBackend):
            def qubit_report(self,flow,context_id):
                rows=list(csv.reader(io.StringIO(super().qubit_report(flow,context_id).decode())))
                rows[2][-1]='UnknownStandardWarning'
                stream=io.StringIO(newline='');csv.writer(stream).writerows(rows)
                return stream.getvalue().encode()
        self.complete_nd();handle=self.start('qubit')
        with self.assertRaises(TaskError):FlaggedBackend(actor_id=ACTOR).run_device(self.flow,'qubit')
        self.assertTrue(any(r.get('standard_id') and any(r['instrument_messages'].values()) for r in handle.state['results'].values()))
        self.assertEqual(len(handle.state['imports']),1)
        self.assertTrue(self.flow.state['recovery_required'])
        self.assertEqual(self.remaining(),196.5)

    def test_qubit_pending_standard_unknown_then_notperformed_retains_stock_and_can_abort(self):
        self.complete_nd();handle=self.start('qubit');self.backend._claim(handle)
        standard=handle.state['definition']['protocol']['assay']['standards'][0]['id']
        self.backend._begin_preparation(handle,'standard',standard)
        pending=copy.deepcopy(handle.state['pending_operation'])
        self.flow.act('cancel',ACTOR,reason=REASON)
        self.flow.act('resolve_device',ACTOR,device='qubit',pending_resolution={'intent_id':pending['intent_id'],'outcome':'unknown'},device_valid=False,reason=REASON)
        self.assertEqual(self.flow.state['bookings'][pending['intent_id']]['outcome'],'unknown')
        self.flow.act('resolve_device',ACTOR,device='qubit',pending_resolution={'intent_id':pending['intent_id'],'outcome':'not_performed'},device_valid=False,reason=REASON)
        handle.act('dispose_vessel',ACTOR,vessel_id=pending['vessel_id'],observed_vessel_id=pending['vessel_id'],reason=REASON)
        self.flow.act('reconcile',ACTOR,observations=self.flow.inventory_observations(),workspace_clear=True)
        for identity,m in self.flow.state['inventory']['materials'].items():
            if m['disposition'] not in {'consumed','discarded'}:
                self.flow.act('set_disposition',ACTOR,material_id=identity,disposition='retained' if m['kind'] in {'product','reagent'} else 'discarded',reason=REASON)
        self.flow.act('confirm_inventory',ACTOR,observations=self.flow.inventory_observations())
        self.flow.act('finish_cancel',ACTOR,workspace_clear=True)
        self.assertEqual(self.flow.state['status'],'cancelled');self.assertEqual(self.remaining(),198.5)


if __name__=='__main__':unittest.main()
