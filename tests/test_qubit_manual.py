"""Synthetic Qubit preparations, calibration, import and cross-device recovery."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError, inventory_observations, original_location
from nanodrop_manual import Workflow as NanoDrop
from qubit_manual import Workflow, SOURCE, calibration_binding, next_preparation, load_profile
from qubit_csv import parse_report
from run_qubit_manual import (ACTOR, begin_preparation, confirm_preparation, measure,
                              prepare_standards, synthetic_report)

RUN_ID = 'SYN-QB-FIXTURE'
FIXTURE = ROOT / 'tests/fixtures/qubit-4/synthetic-report.csv'


class QubitTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='qubit-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.path = self.folder / 'tasks.sqlite3'
        self.journal = Journal(self.path)
        self.flow = Workflow.create(self.journal, run_id=RUN_ID)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def claim(self, flow=None):
        flow = flow or self.flow
        flow.act('rack_ready', ACTOR, observations=inventory_observations(flow.state))
        flow.act('workspace_clear', ACTOR, confirmed=True)
        flow.act('claim', ACTOR)

    def take(self, sample_id='Sample01', flow=None):
        flow = flow or self.flow
        sample = flow.state['samples'][sample_id]
        flow.act('take', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                 rack_id=sample['location']['rack_id'], place_id=sample['location']['place_id'])

    def place(self, sample_id='Sample01', flow=None):
        flow = flow or self.flow
        sample = flow.state['samples'][sample_id]
        flow.act('place', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                 **{k: v for k, v in original_location(flow.state, sample).items() if k != 'kind'})

    def prepare_samples(self, flow=None):
        flow = flow or self.flow
        for sample_id in flow.state['samples']:
            self.take(sample_id, flow)
            begin_preparation(flow, 'sample', sample_id)
            confirm_preparation(flow)
            self.place(sample_id, flow)

    def measure_samples(self, flow=None):
        flow = flow or self.flow
        flow.act('advance_time', ACTOR, seconds=2)
        for key, preparation in flow.state['preparations'].items():
            if preparation['kind'] == 'sample':
                measure(flow, key)

    def measured(self):
        self.claim()
        prepare_standards(self.flow)
        self.prepare_samples()
        self.measure_samples()

    def dispose(self, flow=None):
        flow = flow or self.flow
        for key, vessel in flow.state['derived_vessels'].items():
            if vessel['location']['kind'] != 'discarded':
                flow.act('dispose_vessel', ACTOR, vessel_id=key, observed_vessel_id=key,
                         reason='Explicit synthetic disposal')

    def import_content(self, content=None, flow=None):
        flow = flow or self.flow
        content = FIXTURE.read_bytes() if content is None else content
        flow.act('import_results', ACTOR, artifact=content, file_name='synthetic-report.csv')
        return digest(content)

    def review(self, flow=None):
        (flow or self.flow).act('review_results', ACTOR, decision='accepted', reason='Synthetic decision')

    def reconcile(self, flow=None, **changes):
        flow = flow or self.flow
        values = {'observations': inventory_observations(flow.state),
                  'workspace_clear': False, 'calibration_still_valid': True}
        flow.act('reconcile', ACTOR, **{**values, **changes})

    def sample_preparation(self, flow=None):
        flow = flow or self.flow
        return flow.state['preparations'][flow.state['active_preparations']['sample:Sample01']]

    def test_full_run_preserves_original_slots_and_uses_each_transfer_once(self):
        self.measured()
        self.dispose()
        checksum = self.import_content()
        self.review()
        self.flow.act('release', ACTOR, workspace_clear=True)
        report = self.flow.report()
        self.assertTrue(report['passed'])
        self.assertTrue(report['order_restored'])
        self.assertEqual(len(report['preparations']), 5)
        self.assertEqual(len(report['transfers']), 5)
        self.assertEqual(len(report['measurements']), 5)
        self.assertEqual(report['samples']['Sample01']['remaining_volume_ul'], 38)
        self.assertIsNone(report['samples']['Sample03']['remaining_volume_ul'])
        self.assertIn('profile_declaration', report['samples']['Sample01']['initial_volume_source'])
        self.assertEqual(report['logical_time_s'], 4)
        self.assertEqual(self.journal.artifact(checksum), FIXTURE.read_bytes())
        self.assertEqual(self.journal.owners(), {})
        standards = report['calibration']['standard_measurements']
        self.assertEqual(set(standards), {'SYN.StandardLow', 'SYN.StandardHigh'})
        for identity, result in report['results'].items():
            self.assertEqual(result['calibration_id'], report['calibration']['id'])
            self.assertEqual(result['calibration_binding_source'], 'workflow_record')
            self.assertEqual(result['vessel_id'], report['preparations'][result['preparation_id']]['vessel_id'])
            self.assertEqual(result['instrument_messages']['Warnings'], 'SYNTHETIC TEST DATA')
            if result['record_type'] == 'standard':
                self.assertEqual(standards[result['standard_id']], identity)
        for key in ['network_executed', 'hardware_executed', 'robot_motion_executed',
                    'real_export_validated', 'calibration_curve_computed',
                    'external_device_recalibration_detectable', 'cf01_continuation_executed']:
            self.assertFalse(report[key], key)

    def test_transfer_is_a_record_and_does_not_invent_an_aliquot_vessel(self):
        self.claim()
        self.take()
        begin_preparation(self.flow, 'sample', 'Sample01')
        tube = self.flow.state['pending_operation']['vessel_id']
        self.assertEqual(self.flow.state['derived_vessels'][tube]['content_state'], 'uncertain')
        self.assertIsNone(self.flow.report()['samples']['Sample01']['remaining_volume_ul'])
        confirm_preparation(self.flow)
        self.assertEqual(list(self.flow.state['derived_vessels']), [tube])
        transfer = next(iter(self.flow.state['transfers'].values()))
        self.assertEqual(transfer['source']['vessel_id'], 'Tube01')
        self.assertEqual(transfer['destination_vessel_id'], tube)
        self.assertEqual(transfer['volume'], {'value': 2, 'unit': 'uL'})

    def test_early_measurement_is_rejected_without_an_event_and_time_is_logged(self):
        self.claim()
        begin_preparation(self.flow, 'standard', 'SYN.StandardLow')
        confirm_preparation(self.flow)
        preparation = next(iter(self.flow.state['preparations'].values()))
        before = self.journal.state(RUN_ID)[1]
        with self.assertRaisesRegex(TaskError, 'incubation minimum'):
            measure(self.flow, preparation['id'])
        self.assertEqual(self.journal.state(RUN_ID)[1], before)
        self.flow.act('advance_time', ACTOR, seconds=2)
        self.assertEqual(self.journal.history(RUN_ID)[-1]['kind'], 'advance_time')
        self.assertEqual(self.flow.state['logical_time_s'], 2)
        measure(self.flow, preparation['id'])

    def test_incomplete_or_mismatched_calibration_is_rejected(self):
        self.claim()
        binding = calibration_binding(self.flow.state)
        with self.assertRaisesRegex(TaskError, 'standard measurements'):
            self.flow.act('approve_calibration', ACTOR, binding=binding,
                          standard_measurements={}, confirmed=True, reason='Synthetic')
        for standard in self.flow.state['definition']['protocol']['assay']['standards']:
            begin_preparation(self.flow, 'standard', standard['id'])
            confirm_preparation(self.flow)
        self.flow.act('advance_time', ACTOR, seconds=2)
        for key in self.flow.state['preparations']:
            measure(self.flow, key)
        mapping = {p['target_id']: p['measurement_id'] for p in self.flow.state['preparations'].values()}
        for key in binding:
            with self.subTest(key=key), self.assertRaisesRegex(TaskError, 'mismatch'):
                self.flow.act('approve_calibration', ACTOR, binding={**binding, key: 'FOREIGN'},
                              standard_measurements=mapping, confirmed=True, reason='Synthetic')
        wrong = dict(zip(mapping, reversed(list(mapping.values()))))
        with self.assertRaisesRegex(TaskError, 'mapping mismatch'):
            self.flow.act('approve_calibration', ACTOR, binding=binding,
                          standard_measurements=wrong, confirmed=True, reason='Synthetic')
        self.flow.act('approve_calibration', ACTOR, binding=binding,
                      standard_measurements=mapping, confirmed=True, reason='Synthetic approval')
        with self.assertRaisesRegex(TaskError, 'One calibration'):
            self.flow.act('approve_calibration', ACTOR, binding=binding,
                          standard_measurements=mapping, confirmed=True, reason='Duplicate')

    def test_calibration_expiration_between_intent_and_confirmation_is_recorded_as_invalid(self):
        self.claim()
        prepare_standards(self.flow)
        self.prepare_samples()
        self.flow.act('advance_time', ACTOR, seconds=2)
        preparation = self.sample_preparation()
        self.flow.act('begin_measurement', ACTOR, preparation_id=preparation['id'],
                      measurement_id=preparation['measurement_id'], observed_vessel_id=preparation['vessel_id'],
                      calibration_id=self.flow.state['calibration']['id'])
        intent = self.flow.state['pending_operation']['intent_id']
        self.flow.act('advance_time', ACTOR, seconds=99)
        self.flow.act('confirm_measurement', ACTOR, intent_id=intent,
                      observed_vessel_id=preparation['vessel_id'], returned_to_holder=True)
        measurement = self.flow.state['measurements'][preparation['measurement_id']]
        self.assertFalse(measurement['valid'])
        self.assertIn('calibration_invalid_at_completion', measurement['invalid_reasons'])
        self.assertEqual(self.flow.state['samples']['Sample01']['remaining_volume_ul'], 38)
        self.assertIsNone(self.flow.state['pending_operation'])
        with self.assertRaisesRegex(TaskError, 'not yet measured'):
            measure(self.flow, preparation['id'])

    def test_expired_calibration_blocks_new_measurement(self):
        self.claim()
        prepare_standards(self.flow)
        self.prepare_samples()
        self.flow.act('advance_time', ACTOR, seconds=101)
        preparation = self.sample_preparation()
        # The incubation window is also enforced; neither expired condition can succeed.
        with self.assertRaises(TaskError):
            measure(self.flow, preparation['id'])
        self.assertNotIn(preparation['measurement_id'], self.flow.state['measurements'])

    def test_historical_measurements_remain_valid_after_calibration_expires(self):
        self.measured()
        self.flow.act('advance_time', ACTOR, seconds=101)
        self.import_content()
        self.review()
        self.assertTrue(all(m['valid'] for m in self.flow.state['measurements'].values()))

    def test_delayed_calibration_approval_cannot_refresh_expired_standard_evidence(self):
        self.claim()
        for standard in self.flow.state['definition']['protocol']['assay']['standards']:
            begin_preparation(self.flow, 'standard', standard['id'])
            confirm_preparation(self.flow)
        self.flow.act('advance_time', ACTOR, seconds=2)
        for key in self.flow.state['preparations']:
            measure(self.flow, key)
        self.flow.act('advance_time', ACTOR, seconds=101)
        mapping = {p['target_id']: p['measurement_id'] for p in self.flow.state['preparations'].values()}
        with self.assertRaisesRegex(TaskError, 'Standard evidence expired'):
            self.flow.act('approve_calibration', ACTOR, binding=calibration_binding(self.flow.state),
                          standard_measurements=mapping, confirmed=True, reason='Late synthetic approval')
        self.assertEqual(self.flow.state['calibration']['status'], 'pending')

    def test_cancel_can_retire_an_explicitly_unperformed_measurement(self):
        self.claim()
        prepare_standards(self.flow)
        self.prepare_samples()
        self.flow.act('advance_time', ACTOR, seconds=2)
        preparation = self.sample_preparation()
        self.flow.act('begin_measurement', ACTOR, preparation_id=preparation['id'],
                      measurement_id=preparation['measurement_id'], observed_vessel_id=preparation['vessel_id'],
                      calibration_id=self.flow.state['calibration']['id'])
        intent = self.flow.state['pending_operation']['intent_id']
        self.flow.act('cancel', ACTOR, reason='Synthetic interruption before measurement')
        self.reconcile(pending_resolution={'intent_id': intent, 'outcome': 'not_performed'})
        self.dispose()
        self.flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.assertEqual(self.flow.state['samples']['Sample01']['remaining_volume_ul'], 38)
        self.assertNotIn(preparation['measurement_id'], self.flow.state['measurements'])
        self.assertFalse(self.flow.report()['passed'])

    def test_nonfinite_clock_advancement_cannot_change_the_stored_time(self):
        self.claim()
        for value in [0, -1, True, float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(TaskError):
                self.flow.act('advance_time', ACTOR, seconds=value)
        self.flow.act('advance_time', ACTOR, seconds=1e308)
        revision = self.journal.state(RUN_ID)[1]
        with self.assertRaises(TaskError):
            self.flow.act('advance_time', ACTOR, seconds=1e308)
        self.assertEqual(self.journal.state(RUN_ID)[1], revision)
        self.assertEqual(self.flow.state['logical_time_s'], 1e308)

    def test_incubation_maximum_and_task_deadline_do_not_invent_measurements(self):
        self.claim()
        begin_preparation(self.flow, 'standard', 'SYN.StandardLow')
        confirm_preparation(self.flow)
        self.flow.act('advance_time', ACTOR, seconds=21)
        with self.assertRaisesRegex(TaskError, 'incubation maximum'):
            measure(self.flow, next(iter(self.flow.state['preparations'])))
        self.flow.act('advance_time', ACTOR, seconds=180)
        self.assertEqual(self.flow.state['recovery_required'], 'deadline_exceeded')
        self.assertEqual(self.flow.state['measurements'], {})
        self.assertTrue(self.journal.owners())

    def test_reported_original_is_not_corrected_twice_and_missing_original_is_derived(self):
        self.measured()
        self.import_content()
        by_sample = {r['sample_id']: r for r in self.flow.state['results'].values() if r['sample_id']}
        self.assertEqual(by_sample['Sample02']['metrics']['original_concentration']['basis'], 'reported')
        self.assertAlmostEqual(by_sample['Sample02']['metrics']['original_concentration']['value'], 10)
        self.assertAlmostEqual(by_sample['Sample02']['metrics']['tube_concentration']['value'], 0.2)
        first = by_sample['Sample01']['metrics']['original_concentration']
        self.assertEqual(first['basis'], 'derived')
        self.assertAlmostEqual(first['value'], 15)
        self.assertEqual(first['sample_volume_ul'], 2)
        self.assertEqual(first['assay_total_volume_ul'], 100)
        self.assertIn('tube_concentration_ng_ul', first['formula'])

    def test_missing_standard_foreign_duplicate_wrong_metadata_and_volume_are_quarantined(self):
        self.measured()
        original = FIXTURE.read_bytes()
        lines = original.splitlines(keepends=True)
        cases = [
            ('missing_measurement', b''.join(line for line in lines if b',standard,' not in line)),
            ('foreign_measurement', original.replace(b'.P0003.M01', b'.P9999.M01')),
            ('duplicate_measurement', original + lines[-1]),
            ('kitlot_mismatch', original.replace(b'SYN.KIT.001', b'FOREIGN')),
            ('assayrevision_mismatch', original.replace(b'Concentration,1,', b'Concentration,2,')),
            ('sample_volume_mismatch', original.replace(b',2,SYNTHETIC', b',3,SYNTHETIC')),
            ('unit', original.replace(b'ng/uL', b'mg/L')),
            ('numeric', original.replace(b',0.1,ng/uL,', b',NaN,ng/uL,'))]
        for expected, content in cases:
            with self.subTest(expected=expected):
                checksum = self.import_content(content)
                record = self.flow.state['imports'][checksum]
                self.assertEqual(record['status'], 'quarantined')
                self.assertIn(expected, ' '.join(record['issues']))
                self.assertEqual(self.journal.artifact(checksum), content)
        self.assertEqual(self.flow.state['results'], {})

    def test_import_idempotence_and_conflicts_do_not_overwrite_results(self):
        self.measured()
        checksum = self.import_content()
        revision = self.journal.state(RUN_ID)[1]
        self.import_content()
        self.assertEqual(self.journal.state(RUN_ID)[1], revision)
        conflict = self.import_content(FIXTURE.read_bytes().replace(b'SYNTHETIC TEST DATA', b'SYNTHETIC CONFLICT'))
        with self.assertRaisesRegex(TaskError, 'quarantined'):
            self.review()
        self.flow.act('discard_import', ACTOR, sha256=conflict, reason='Synthetic conflict acknowledged')
        self.review()
        self.assertEqual(len(self.flow.state['results']), 5)
        self.assertEqual(self.journal.artifact(checksum), FIXTURE.read_bytes())

    def test_derived_vessels_block_release_and_cancel_until_disposal_is_confirmed(self):
        self.measured()
        self.import_content()
        self.review()
        with self.assertRaisesRegex(TaskError, 'derived vessel'):
            self.flow.act('release', ACTOR, workspace_clear=True)
        self.flow.act('cancel', ACTOR, reason='Synthetic cancellation')
        self.reconcile()
        with self.assertRaisesRegex(TaskError, 'derived vessel'):
            self.flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.dispose()
        self.flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.assertEqual(self.flow.state['status'], 'cancelled')
        self.assertEqual(self.journal.owners(), {})

    def test_unknown_and_unperformed_preparation_need_new_ids_and_explicit_disposal(self):
        self.claim()
        self.take()
        pending = begin_preparation(self.flow, 'sample', 'Sample01')
        old = self.sample_preparation()
        self.flow.close()
        self.flow = Workflow.open(self.journal, RUN_ID)
        self.reconcile(pending_resolution={'intent_id': pending['intent_id'], 'outcome': 'unknown'})
        self.assertEqual(self.flow.state['recovery_required'], 'operation_outcome_unknown')
        self.assertIsNone(self.flow.report()['samples']['Sample01']['remaining_volume_ul'])
        self.reconcile(pending_resolution={'intent_id': pending['intent_id'], 'outcome': 'not_performed'})
        with self.assertRaisesRegex(TaskError, 'Discard'):
            begin_preparation(self.flow, 'sample', 'Sample01')
        self.dispose()
        begin_preparation(self.flow, 'sample', 'Sample01')
        new = self.sample_preparation()
        self.assertNotEqual(old['id'], new['id'])
        self.assertNotEqual(old['vessel_id'], new['vessel_id'])
        self.assertNotEqual(old['measurement_id'], new['measurement_id'])
        confirm_preparation(self.flow)
        self.assertEqual(self.flow.state['samples']['Sample01']['remaining_volume_ul'], 38)
        self.assertNotIn(old['measurement_id'], self.flow.state['planned_measurements'].values())

    def test_missing_derived_vessel_prevents_reconciliation(self):
        self.claim()
        pending = begin_preparation(self.flow, 'standard', 'SYN.StandardLow')
        self.flow.close()
        self.flow = Workflow.open(self.journal, RUN_ID)
        observed = inventory_observations(self.flow.state)
        self.assertEqual(observed[-1]['vessel_id'], pending['vessel_id'])
        with self.assertRaises(ObservationError):
            self.reconcile(observations=observed[:-1], pending_resolution={'intent_id': pending['intent_id'], 'outcome': 'not_performed'})
        self.assertIsNotNone(self.flow.state['recovery_required'])

    def test_clock_mode_and_event_time_survive_restart(self):
        self.claim()
        self.flow.act('advance_time', ACTOR, seconds=1)
        self.flow.close()
        with self.assertRaisesRegex(TaskError, 'Clock mode'):
            Workflow.open(self.journal, RUN_ID, clock_mode='wall_clock')
        with Journal(self.path, clock=lambda: 9999999999) as other:
            flow = Workflow.open(other, RUN_ID)
            self.assertEqual(flow.state['logical_time_s'], 1)
            self.assertEqual(flow.state['recovery_required'], 'session_restarted')

    def test_held_derived_vessel_prevents_original_pickup_after_reconciliation(self):
        self.claim()
        pending = begin_preparation(self.flow, 'standard', 'SYN.StandardLow')
        confirm_preparation(self.flow)
        self.flow.close()
        self.flow = Workflow.open(self.journal, RUN_ID)
        observations = inventory_observations(self.flow.state)
        tube = next(item for item in observations if item['vessel_id'] == pending['vessel_id'])
        tube['location'] = {'kind': 'operator', 'actor_id': ACTOR}
        self.reconcile(observations=observations)
        revision = self.journal.state(RUN_ID)[1]
        with self.assertRaisesRegex(TaskError, 'held vessel'):
            self.take()
        self.assertEqual(self.journal.state(RUN_ID)[1], revision)
        sample = self.flow.state['samples']['Sample01']
        self.assertEqual(sample['location'], original_location(self.flow.state, sample))

    def test_stale_preparation_confirmation_and_wrong_tube_do_not_consume_original(self):
        self.claim()
        self.take()
        pending = begin_preparation(self.flow, 'sample', 'Sample01')
        with self.assertRaises(ObservationError):
            self.flow.act('confirm_preparation', ACTOR, intent_id=pending['intent_id'],
                          observed_vessel_id='FOREIGN', observed_sample_id='Sample01',
                          volume_ul=2, assay_total_volume_ul=100, mixed=True)
        self.assertEqual(self.flow.state['transfers'], {})
        self.assertEqual(self.flow.state['samples']['Sample01']['remaining_volume_ul'], 40)

    def test_hard_process_exit_recovers_known_assay_tube_and_binds_transfer_once(self):
        db = self.folder / 'crash.sqlite3'
        script = '''
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'scripts'))
from manual_tasks import Journal
from manual_workflow import inventory_observations
from qubit_manual import Workflow
from run_qubit_manual import ACTOR,begin_preparation
j=Journal(sys.argv[1]);f=Workflow.create(j,run_id='SYN-QB-CRASH')
f.act('rack_ready',ACTOR,observations=inventory_observations(f.state))
f.act('workspace_clear',ACTOR,confirmed=True);f.act('claim',ACTOR)
s=f.state['samples']['Sample01']
f.act('take',ACTOR,sample_id='Sample01',observed_sample_id='Sample01',rack_id=s['location']['rack_id'],place_id=s['original_place_id'])
begin_preparation(f,'sample','Sample01')
os._exit(23)
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(db)], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 23, result.stderr)
        with Journal(db) as journal:
            with self.assertRaisesRegex(TaskError, 'explicit resume'):
                Workflow.open(journal, 'SYN-QB-CRASH')
            flow = Workflow.open(journal, 'SYN-QB-CRASH', resume=True)
            pending = flow.state['pending_operation']
            self.assertIn(pending['vessel_id'], flow.state['derived_vessels'])
            resolution = {'intent_id': pending['intent_id'], 'outcome': 'performed',
                          'observed_vessel_id': pending['vessel_id'], 'observed_sample_id': 'Sample01',
                          'volume_ul': 2, 'assay_total_volume_ul': 100, 'mixed': True}
            self.reconcile(flow, pending_resolution=resolution)
            self.assertEqual(flow.state['samples']['Sample01']['remaining_volume_ul'], 38)
            self.assertEqual(len(flow.state['transfers']), 1)
            with self.assertRaises(TaskError):
                flow.act('confirm_preparation', ACTOR, **{k: v for k, v in resolution.items() if k != 'outcome'})
            self.assertEqual(flow.state['samples']['Sample01']['remaining_volume_ul'], 38)


class SharedWorkflowTests(unittest.TestCase):
    def test_nanodrop_behavior_matches_pre_extraction_snapshot(self):
        from run_nanodrop_manual import run_demo
        from manual_workflow_snapshot import project
        with tempfile.TemporaryDirectory(prefix='nd-regression-', dir=ROOT / 'exports') as folder:
            with Journal(Path(folder) / 'tasks.sqlite3') as store:
                flow = NanoDrop.create(store, run_id='SYN-ND-REGRESSION')
                run_demo(flow)
                expected = json.loads((ROOT / 'tests/fixtures/nanodrop/before-qubit-extraction.json').read_text())
                self.assertEqual(project(flow.report()), expected)

    def test_runner_format_guards_and_changed_core_source_apply_to_both_adapters(self):
        with tempfile.TemporaryDirectory() as folder, Journal(Path(folder) / 'tasks.sqlite3') as store:
            nano = NanoDrop.create(store, run_id='SYN-ND-FORMAT')
            qubit = Workflow.create(store, run_id='SYN-QB-FORMAT')
            for adapter, alien in [(NanoDrop, qubit), (Workflow, nano)]:
                with self.subTest(adapter=adapter.__module__):
                    with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
                        adapter.open(store, alien.run_id)
                    with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
                        adapter(store, alien.run_id, None)
                    own = nano if adapter is NanoDrop else qubit
                    wrapper = adapter(store, own.run_id, own.session)
                    wrapper.run_id = alien.run_id
                    with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
                        wrapper.act('claim', ACTOR)
                    with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
                        wrapper.report()
            import manual_workflow
            original_digest = manual_workflow.digest
            core = (ROOT / 'scripts/manual_workflow.py').read_bytes()
            for flow in [nano, qubit]:
                flow.close()
                adapter = type(flow)
                with patch.object(manual_workflow, 'digest', side_effect=lambda data: '0' * 64 if data == core else original_digest(data)):
                    with self.assertRaisesRegex(TaskError, 'manual_workflow.py'):
                        adapter.open(store, flow.run_id)

    def test_same_vessel_ids_conflict_even_with_different_racks_and_instruments(self):
        with tempfile.TemporaryDirectory() as folder, Journal(Path(folder) / 'tasks.sqlite3') as store:
            nano = NanoDrop.create(store, run_id='SYN-ND-OWNER')
            nano.act('rack_ready', ACTOR, observations=inventory_observations(nano.state))
            profile = json.loads(SOURCE.read_text())
            profile['rack']['id'] = 'SYN.DifferentRack'
            profile['workspace']['id'] = 'SYN.DifferentWorkArea'
            qubit = Workflow.create(store, profile, 'SYN-QB-COLLISION')
            with self.assertRaisesRegex(TaskError, 'vessel:Tube'):
                qubit.act('rack_ready', ACTOR, observations=inventory_observations(qubit.state))
            self.assertEqual(qubit.state['resources'], [])
            self.assertTrue(all(owner == nano.run_id for owner in store.owners().values()))
            for sample in profile['samples']:
                sample['vessel_id'] += '-independent'
            independent = Workflow.create(store, profile, 'SYN-QB-INDEPENDENT')
            independent.act('rack_ready', ACTOR, observations=inventory_observations(independent.state))
            self.assertEqual(len(store.owners()), 12)

    def test_programming_type_errors_are_not_relabelled_as_user_input_errors(self):
        with tempfile.TemporaryDirectory() as folder, Journal(Path(folder) / 'tasks.sqlite3') as store:
            flow = Workflow.create(store, run_id='SYN-QB-TYPEERROR')
            def broken(state, actor_id):
                raise TypeError('Deliberate internal test error')
            with patch.object(flow, '_check_deadline', side_effect=broken):
                with self.assertRaises(TypeError):
                    flow.act('check_deadline', ACTOR)

    def test_nanodrop_clock_mismatch_and_missing_runtime_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tasks.sqlite3'
            with Journal(path, clock=lambda: 1000) as store:
                flow = NanoDrop.create(store, run_id='SYN-ND-CLOCK')
                flow.close()
            with Journal(path) as store:
                with self.assertRaisesRegex(TaskError, 'Clock mode mismatch'):
                    NanoDrop.open(store, 'SYN-ND-CLOCK')
                self.assertFalse(NanoDrop(store, 'SYN-ND-CLOCK', None).report()['passed'])
            with Journal(path, clock=lambda: 1000) as store:
                state, revision = store.state('SYN-ND-CLOCK')
                del state['definition']['runtime_source_files']
                store.append('SYN-ND-CLOCK', revision, 'synthetic_legacy_manifest_fixture', {}, state)
                with self.assertRaisesRegex(TaskError, 'manifest missing'):
                    NanoDrop.open(store, 'SYN-ND-CLOCK')
                self.assertFalse(NanoDrop(store, 'SYN-ND-CLOCK', None).report()['passed'])


class QubitProfileAndParserTests(unittest.TestCase):
    def test_profile_rejects_inconsistent_volumes_times_and_unsupported_parameters(self):
        base = json.loads(SOURCE.read_text())
        for key, value in [('sample_volume_ul', True), ('sample_volume_ul', float('nan')),
                           ('assay_total_volume_ul', 1), ('incubation_max_s', 1),
                           ('task_deadline_s', 3), ('calibration_validity_s', 0)]:
            data = copy.deepcopy(base)
            data['parameters'][key] = value
            with self.subTest(key=key), self.assertRaises(TaskError):
                load_profile(data)

    def test_synthetic_marker_units_and_finite_values_are_required(self):
        content = FIXTURE.read_bytes()
        for invalid in [content.replace(b'solidcraftbot.synthetic-qubit-report/1', b'native-export'),
                        content.replace(b'ng/uL', b'mg/L'),
                        content.replace(b',0.1,ng/uL,', b',Infinity,ng/uL,')]:
            with self.subTest(invalid=invalid[:60]), self.assertRaises(TaskError):
                parse_report(invalid)
        report = parse_report(content)
        self.assertEqual(len(report['rows']), 5)
        self.assertNotIn('Calibration ID', content.decode())


class QubitCommandLineTests(unittest.TestCase):
    def test_demo_and_cross_runner_status_report_session_rejection(self):
        from run_nanodrop_manual import DEFAULT_STORE as nd_store
        from run_qubit_manual import DEFAULT_STORE as qb_store
        self.assertEqual(nd_store, qb_store)
        with tempfile.TemporaryDirectory(prefix='qb-cli-', dir=ROOT / 'exports') as folder:
            folder = Path(folder)
            db = folder / 'tasks.sqlite3'
            def cli(script, *args):
                return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / script),
                                       '--store', str(db), *args], cwd=ROOT,
                                      capture_output=True, text=True, timeout=20)
            result = cli('run_qubit_manual.py', 'demo', '--run-id', 'SYN-QB-CLI')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'completed')
            with Journal(db) as store:
                nano = NanoDrop.create(store, run_id='SYN-ND-CLI-FORMAT')
                nano.close()
            for script, run_id in [('run_nanodrop_manual.py', 'SYN-QB-CLI'),
                                   ('run_qubit_manual.py', 'SYN-ND-CLI-FORMAT')]:
                for command in ['status', 'report', 'session']:
                    with self.subTest(script=script, command=command):
                        response = cli(script, command, run_id)
                        self.assertEqual(response.returncode, 1)
                        self.assertIn('Wrong workflow format', response.stderr)


if __name__ == '__main__':
    unittest.main()
