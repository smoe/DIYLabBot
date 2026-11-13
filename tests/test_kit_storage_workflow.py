"""A serial durable fixture, deliberately outside global stock and hardware."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import kit_storage_workflow as storage
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError

ACTOR = 'SYN.Storage.Operator'


class StorageFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kit-storage-workflow-')
        self.path = Path(self.temp.name)/'workflows.sqlite3'
        self.journal = Journal(self.path)
        self.runner = storage.StorageRunner.init(self.journal, 'Test.World01')
        self.count = 0

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def observation(self, runner=None, *, phase=None, leg=None):
        self.count += 1
        runner = runner or self.runner
        return storage.synthetic_observation(runner.state, 'Observation'+str(self.count), phase=phase, leg=leg)

    def ready(self, runner=None):
        runner = runner or self.runner
        return runner.accept_initial(ACTOR, self.observation(runner))

    def step(self, kind, runner=None, operation=None):
        runner = runner or self.runner
        operation = operation or 'Leg'+str(runner.state['leg'])+'.'+kind
        runner.intent(ACTOR, operation, kind)
        phase, leg = runner._after(runner.state, kind)
        return runner.confirm(ACTOR, operation, self.observation(runner, phase=phase, leg=leg))

    def finish(self, runner=None):
        runner = runner or self.runner
        while runner.state['leg'] < 2:
            for kind in ('pickup', 'setdown', 'release'):
                self.step(kind, runner)
        runner.complete(ACTOR, self.observation(runner))
        return runner.report()

    def test_full_route_keeps_ids_and_contents_and_records_intent_before_every_confirmation(self):
        initial = self.runner.report()['scene']
        self.ready()
        report = self.finish()
        self.assertTrue(report['passed'])
        self.assertEqual(report['scene'], initial)
        self.assertEqual(report['leg'], 2)
        self.assertEqual(len(report['operations']), 6)
        self.assertEqual(report['resources'], [])
        self.assertFalse(report['location_uncertain'])
        self.assertEqual(self.journal.owners(), {})
        self.assertEqual(report['route'][0], report['route'][-1])
        for name in ['cross_run_inventory', 'quantity_ledger', 'global_stock_fencing', 'robot_motion_executed',
                     'hardware_executed', 'network_executed', 'grasp_qualified', 'load_qualified', 'safety_function_qualified']:
            self.assertIs(report[name], False)
        for operation in report['operations']:
            before = next(e for e in report['trace'] if e['kind'] == operation['kind']+'_intent'
                          and e['payload']['operation_id'] == operation['operation_id'])
            after = next(e for e in report['trace'] if e['kind'] == 'operation_confirmed'
                         and e['payload']['operation_id'] == operation['operation_id'])
            self.assertLess(before['sequence'], after['sequence'])
            self.assertEqual(before['state']['pending']['operation_id'], operation['operation_id'])
            self.assertEqual(after['payload']['observation']['evidence'], 'synthetic_observation')
            self.assertEqual(after['payload']['observation']['fixture_id'], self.runner.fixture_id)
        self.assertNotIn('volumes', report)
        self.assertNotIn('stock', report)

    def test_fixture_init_never_resets_existing_created_or_completed_world(self):
        first = self.journal.history(self.runner.run_id)
        with self.assertRaisesRegex(TaskError, 'already exists'):
            storage.StorageRunner.init(self.journal, self.runner.fixture_id)
        self.assertEqual(self.journal.history(self.runner.run_id), first)
        self.ready(); self.finish()
        final = self.journal.history(self.runner.run_id)
        with self.assertRaisesRegex(TaskError, 'already exists'):
            storage.StorageRunner.init(self.journal, self.runner.fixture_id)
        self.assertEqual(self.journal.history(self.runner.run_id), final)
        self.assertEqual(self.runner.run_id, storage.run_id_for(self.runner.fixture_id))

    def test_shaped_return_without_six_receipts_cannot_complete_and_missing_or_reordered_receipts_fail_report(self):
        self.ready()
        state, revision = self.journal.get_current(self.runner.run_id)
        state.update(phase='returned', leg=2)
        self.journal.append(self.runner.run_id, revision, 'synthetic_bad_projection', {}, state)
        with self.assertRaisesRegex(TaskError, 'receipts'):
            self.runner.complete(ACTOR, storage.synthetic_observation(state, 'NotEvidence'))
        for mutation in ('missing', 'reordered', 'missing_observation'):
            with self.subTest(mutation=mutation):
                runner = storage.StorageRunner.init(self.journal, 'Receipts.'+mutation)
                self.ready(runner); self.finish(runner)
                state, revision = self.journal.get_current(runner.run_id)
                if mutation == 'missing': state['operations'].pop(1)
                elif mutation == 'reordered': state['operations'][1:3] = reversed(state['operations'][1:3])
                else: state['operations'][1]['observation_id'] = 'NoSuchObservation'
                self.journal.append(runner.run_id, revision, 'synthetic_bad_receipts', {}, state)
                with self.assertRaisesRegex(TaskError, 'receipt'): runner.report()

    def test_two_explicit_fixture_ids_are_separate_worlds_with_disjoint_reservations(self):
        self.ready()
        other = storage.StorageRunner.init(self.journal, 'Test.World02')
        self.ready(other)
        self.assertEqual(self.runner.report()['scene']['carrier_id'], other.report()['scene']['carrier_id'])
        self.assertFalse(set(self.runner.state['resources']) & set(other.state['resources']))
        self.assertEqual(set(self.journal.owners().values()), {self.runner.run_id, other.run_id})

    def test_an_observation_from_another_world_cannot_confirm_identical_source_ids(self):
        self.ready()
        self.runner.intent(ACTOR, 'Pick', 'pickup')
        observation = self.observation(phase='captured')
        observation['fixture_id'] = 'Test.OtherWorld'
        with self.assertRaises(ObservationError):
            self.runner.confirm(ACTOR, 'Pick', observation)
        self.assertEqual(self.runner.state['status'], 'held')
        self.assertEqual(self.runner.state['phase'], 'ready')
        self.assertEqual(self.runner.state['pending']['operation_id'], 'Pick')

    def test_wrong_carrier_content_material_slot_or_occupied_target_preserves_pending_and_locks(self):
        for mutation in ['carrier', 'missing_content', 'foreign_content', 'slot', 'material', 'occupied_target', 'support', 'empty']:
            with self.subTest(mutation=mutation):
                runner = storage.StorageRunner.init(self.journal, 'Mismatch.'+mutation)
                self.ready(runner); self.step('pickup', runner)
                runner.intent(ACTOR, 'Place', 'setdown')
                observation = self.observation(runner, phase='supported')
                if mutation == 'carrier': observation['carrier_id'] = 'AnotherCarrier'
                elif mutation == 'missing_content': observation['contents'].pop()
                elif mutation == 'foreign_content': observation['contents'][0]['id'] = 'ForeignContent'
                elif mutation == 'slot': observation['contents'][0]['slot_id'] = 'OtherSlot'
                elif mutation == 'material': observation['contents'][0]['material_id'] = 'OtherMaterial'
                elif mutation == 'occupied_target': observation['places'][runner.state['definition']['route'][1]] = 'OtherCarrier'
                elif mutation == 'support': observation['supported'] = False
                else: observation['gripper']['empty'] = True
                resources = runner.state['resources']
                with self.assertRaises(ObservationError): runner.confirm(ACTOR, 'Place', observation)
                self.assertEqual(runner.state['status'], 'held')
                self.assertEqual(runner.state['phase'], 'captured')
                self.assertEqual(runner.state['pending']['operation_id'], 'Place')
                self.assertEqual(runner.state['resources'], resources)
                self.assertTrue(all(self.journal.owners()[r] == runner.run_id for r in resources))
                with self.assertRaisesRegex(TaskError, 'reconciliation'):
                    runner.intent(ACTOR, 'NoFollowup', 'release')

    def test_duplicate_operations_and_out_of_sequence_release_never_repeat_effects(self):
        self.ready(); self.step('pickup', operation='Pick')
        before = self.journal.history(self.runner.run_id)
        with self.assertRaises(TaskError): self.runner.intent(ACTOR, 'Pick', 'pickup')
        with self.assertRaises(TaskError): self.runner.confirm(ACTOR, 'Pick', self.observation(phase='captured'))
        with self.assertRaises(TaskError): self.runner.intent(ACTOR, 'ReleaseTooEarly', 'release')
        with self.assertRaises(TaskError): self.runner.complete(ACTOR, self.observation())
        self.assertEqual(self.journal.history(self.runner.run_id), before)
        self.assertEqual(self.runner.state['phase'], 'captured')

    def test_support_does_not_imply_gripper_release(self):
        self.ready(); self.step('pickup'); self.step('setdown')
        scene = self.runner.report()['scene']
        self.assertTrue(scene['supported'])
        self.assertFalse(scene['gripper']['empty'])
        self.assertEqual(scene['gripper']['carrier_id'], scene['carrier_id'])
        self.assertEqual(scene['places'][scene['location']], scene['carrier_id'])
        self.assertEqual(self.runner.state['leg'], 0)
        with self.assertRaises(TaskError): self.runner.intent(ACTOR, 'PickAgain', 'pickup')

    def test_resource_conflict_rolls_back_all_reservations_and_initial_acknowledgement(self):
        resources = storage.resource_ids(self.runner.fixture_id, self.runner.state['definition'])
        with Journal(self.path) as other:
            other.create('ForeignReservation', {'resources': []})
            other.append('ForeignReservation', 1, 'reserve', {}, {'resources': [resources[-1]]})
        with self.assertRaisesRegex(TaskError, 'Resource reserved'): self.ready()
        self.assertEqual(self.runner.state['phase'], 'initial')
        self.assertEqual(self.runner.state['resources'], [])
        self.assertEqual(self.journal.owners(), {resources[-1]: 'ForeignReservation'})
        self.assertEqual(len(self.journal.history(self.runner.run_id)), 1)

    def test_restart_requires_explicit_resolution_and_keeps_failed_resolution_recoverable(self):
        self.ready(); self.runner.intent(ACTOR, 'Pick', 'pickup'); self.runner.close()
        with self.assertRaisesRegex(TaskError, 'Explicit resume'):
            storage.StorageRunner.open(self.journal, self.runner.fixture_id)
        reopened = storage.StorageRunner.open(self.journal, self.runner.fixture_id, resume=True)
        self.assertEqual(reopened.state['status'], 'held')
        self.assertEqual(reopened.state['pending']['operation_id'], 'Pick')
        with self.assertRaisesRegex(TaskError, 'performed/not_performed'):
            reopened.reconcile(ACTOR, self.observation(reopened), resolution='unchanged')
        with self.assertRaises(ObservationError):
            reopened.reconcile(ACTOR, self.observation(reopened, phase='captured'), resolution='not_performed', operation_id='Pick')
        self.assertEqual(reopened.state['pending']['operation_id'], 'Pick')
        reopened.reconcile(ACTOR, self.observation(reopened), resolution='not_performed', operation_id='Pick')
        self.assertEqual(reopened.state['phase'], 'ready')
        self.assertEqual(reopened.state['operations'][-1]['outcome'], 'not_performed')
        self.assertTrue(reopened.state['resources'])
        with self.assertRaisesRegex(TaskError, 'already used'): reopened.intent(ACTOR, 'Pick', 'pickup')
        self.step('pickup', reopened, 'PickRetry')

    def test_new_session_fences_old_runner_without_mutating_its_token(self):
        self.ready(); old_token = self.runner.session
        with Journal(self.path) as other:
            reopened = storage.StorageRunner.open(other, self.runner.fixture_id, resume=True)
            self.assertNotEqual(old_token, reopened.session)
            with self.assertRaisesRegex(TaskError, 'Stale storage session'):
                self.runner.intent(ACTOR, 'OldPick', 'pickup')
            self.assertEqual(self.runner.session, old_token)
            reopened.reconcile(ACTOR, self.observation(reopened), resolution='unchanged')
            stale, revision = self.journal.get_current(self.runner.run_id)
            reopened.intent(ACTOR, 'NewPick', 'pickup')
            with self.assertRaisesRegex(TaskError, 'changed'):
                self.journal.append(self.runner.run_id, revision, 'stale', {}, stale)
            self.assertEqual(reopened.state['pending']['operation_id'], 'NewPick')

    def test_failed_intent_write_cannot_enable_capture_or_change_the_object_projection(self):
        self.ready(); before = self.journal.history(self.runner.run_id)
        with patch.object(self.journal, 'append', side_effect=RuntimeError('Synthetic disk failure')):
            with self.assertRaisesRegex(RuntimeError, 'disk failure'):
                self.runner.intent(ACTOR, 'UncommittedPick', 'pickup')
        self.assertEqual(self.journal.history(self.runner.run_id), before)
        self.assertIsNone(self.runner.state['pending'])
        with self.assertRaisesRegex(TaskError, 'matching pending'):
            self.runner.confirm(ACTOR, 'UncommittedPick', self.observation(phase='captured'))

    def test_failed_capture_write_preserves_durable_intent_and_blocks_followup(self):
        self.ready(); self.runner.intent(ACTOR, 'Pick', 'pickup')
        with patch.object(self.journal, 'append', side_effect=RuntimeError('Synthetic disk failure')):
            with self.assertRaises(RuntimeError):
                self.runner.confirm(ACTOR, 'Pick', self.observation(phase='captured'))
        self.assertEqual(self.runner.state['phase'], 'ready')
        self.assertEqual(self.runner.state['pending']['operation_id'], 'Pick')
        with self.assertRaises(TaskError): self.runner.intent(ACTOR, 'Place', 'setdown')

    def test_actual_changed_source_bytes_block_resume_action_and_report(self):
        (ROOT/'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='storage-source-pin-', dir=ROOT/'exports') as directory:
            source = Path(directory)/'synthetic-source.json'; source.write_text('{}')
            original = storage.model.runtime_definition
            def definition(spec=None):
                value = original(spec); value['source_files_sha256'][str(source.relative_to(ROOT))] = digest(source.read_bytes())
                return value
            with patch.object(storage.model, 'runtime_definition', side_effect=definition):
                runner = storage.StorageRunner.init(self.journal, 'Source.Drift')
            self.ready(runner); source.write_text('{"changed":true}')
            with self.assertRaisesRegex(TaskError, 'Pinned storage source changed'):
                runner.intent(ACTOR, 'Pick', 'pickup')
            with self.assertRaisesRegex(TaskError, 'Pinned storage source changed'):
                storage.StorageRunner.open(self.journal, runner.fixture_id, resume=True)
            with self.assertRaisesRegex(TaskError, 'Pinned storage source changed'): runner.report()
            self.assertIsNone(runner.state['pending'])
            self.assertTrue(runner.state['resources'])

    def test_hard_process_abort_after_intent_is_not_implicitly_replayed_on_restart(self):
        script = '''import os,sys
sys.path.insert(0, sys.argv[1])
from kit_storage_workflow import Journal, StorageRunner, synthetic_observation
j=Journal(sys.argv[2]); f=StorageRunner.init(j,'Crash.World')
f.accept_initial('SYN.Child',synthetic_observation(f.state,'Initial'))
f.intent('SYN.Child','CrashPick','pickup')
os._exit(73)
'''
        process = subprocess.run([sys.executable, '-c', script, str(ROOT/'scripts'), str(self.path)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 73, process.stderr)
        with Journal(self.path) as fresh:
            runner = storage.StorageRunner.open(fresh, 'Crash.World', resume=True)
            self.assertEqual((runner.state['status'], runner.state['phase']), ('held', 'ready'))
            self.assertEqual(runner.state['pending']['operation_id'], 'CrashPick')
            self.assertEqual(runner.state['operations'], [])
            self.assertTrue(runner.report()['location_uncertain'])
            with self.assertRaisesRegex(TaskError, 'reconciliation'):
                runner.intent(ACTOR, 'ImplicitReplay', 'pickup')
            runner.reconcile(ACTOR, self.observation(runner, phase='captured'), resolution='performed', operation_id='CrashPick')
            self.assertEqual(runner.state['phase'], 'captured')
            self.assertTrue(runner.state['resources'])
            self.assertEqual(sum(e['kind'] == 'pickup_intent' for e in fresh.history(runner.run_id)), 1)
            self.step('setdown', runner); self.step('release', runner)
            report = self.finish(runner)
            self.assertTrue(report['passed'])
            self.assertEqual(report['scene']['location'], report['route'][0])

    def test_cli_demo_and_status_use_same_world_and_reject_reinitialization(self):
        base = [sys.executable, str(ROOT/'scripts/run_kit_storage.py'), '--store', str(self.path), '--fixture-id', 'CLI.World']
        demo = subprocess.run(base+['demo'], capture_output=True, text=True)
        self.assertEqual(demo.returncode, 0, demo.stderr)
        report = json.loads(demo.stdout); self.assertTrue(report['passed'])
        before = self.journal.history(report['run_id'])
        status = subprocess.run(base+['status'], capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)['journal_head_sha256'], report['journal_head_sha256'])
        duplicate = subprocess.run(base+['init'], capture_output=True, text=True)
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn('already exists', duplicate.stderr)
        self.assertEqual(self.journal.history(report['run_id']), before)

    def test_cli_init_and_explicit_resume_do_not_claim_an_observed_or_reserved_fixture(self):
        base = [sys.executable, str(ROOT/'scripts/run_kit_storage.py'), '--store', str(self.path), '--fixture-id', 'CLI.Unobserved']
        for command in ['init', 'resume']:
            process = subprocess.run(base+[command], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads(process.stdout)
            self.assertEqual(report['status'], 'created')
            self.assertFalse(report['initial_confirmed'])
            self.assertTrue(report['location_uncertain'])
            self.assertEqual(report['scene_basis'], 'unobserved_fixture_declaration')
            self.assertEqual(report['resources'], [])
            self.assertIsNone(report['pending'])
            self.assertFalse(report['passed'])


if __name__ == '__main__':
    unittest.main()
