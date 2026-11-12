"""Manual material receipts remain separate from historical synthetic contracts."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError
import material_evidence as evidence
import material_ledger as ledger
from material_workflow import MaterialWorkflow
from test_material_v2 import amount, fixture

ACTOR = 'TEST.ManualObserver'


def context(identity='TEST.Observation', kind='test_fixture'):
    return {'observation_id': identity, 'source_kind': kind,
            'observed_at': {'earliest_utc': '2026-11-12T09:00:00Z', 'latest_utc': '2026-11-12T09:00:01Z'},
            'source_ref': 'TEST.fixture-not-a-real-laboratory-record', 'artifact_sha256': None}


def manual_state(prefix='TEST.Manual'):
    state = fixture(2, prefix)
    state['format'] = 'solidcraftbot.material-workflow-state/3'
    state['definition']['format'] = 'solidcraftbot.material-workflow-definition/3'
    state['clock'] = {'kind': 'test-clock-fixture'}
    state['observation_context'] = context()
    return state


def observe(state, identity):
    state['observation_context'] = context(identity)


def withdraw(state, identity, material, value=5):
    ledger.begin_effect(state, ACTOR, identity, 'withdrawal',
        [{'material_id': material, 'quantity': amount(value), 'consume_all': False}], [], 'test_manual_withdrawal')


class ManualEvidenceTests(unittest.TestCase):
    def test_old_receipt_and_inventory_shapes_remain_exact_even_with_a_manual_context(self):
        for version in [1, 2]:
            state = fixture(version);state['observation_context'] = context(kind='human_observation')
            self.assertEqual(evidence.receipt(state, ACTOR, 'reason', intent_id='I'),
                             {'actor_id': ACTOR, 'reason': 'reason', 'evidence': 'synthetic_input', 'intent_id': 'I'})
            self.assertEqual(evidence.inventory_receipt(state, ACTOR, 'a' * 64),
                             {'actor_id': ACTOR, 'evidence': 'synthetic_input', 'inventory_sha256': 'a' * 64})
            withdraw(state, 'I', 'SYN.Protective.Activation')
            ledger.confirm_effect(state, ACTOR, 'I',
                [{'material_id': 'SYN.Protective.Activation', 'quantity': amount(5)}], [], 'done')
            self.assertEqual(state['bookings']['I']['confirmation'], {
                'actual_inputs': [{'material_id': 'SYN.Protective.Activation', 'quantity': amount(5)}],
                'actual_outputs': [], 'reason': 'done'})
            self.assertNotIn('intent_receipt', state['bookings']['I'])

    def test_manual_receipts_require_stable_explicit_context_and_return_detached_values(self):
        state = manual_state()
        for kind in ['human_observation', 'device_export', 'external_record', 'test_fixture']:
            state['observation_context'] = context(kind=kind)
            result = evidence.receipt(state, ACTOR, 'reason')
            self.assertEqual(result['evidence'], 'test_fixture' if kind == 'test_fixture' else 'manual_observation')
            self.assertEqual(result['observation'], state['observation_context'])
            result['observation']['source_ref'] = 'mutated'
            self.assertNotEqual(state['observation_context']['source_ref'], 'mutated')
        for invalid in [None, {}, {**context(), 'source_kind': 'synthetic_input'},
                        {**context(), 'artifact_sha256': 'bad'}, {**context(), 'source_ref': float('nan')}]:
            state['observation_context'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(TaskError):evidence.receipt(state, ACTOR, 'reason')

    def test_missing_context_rolls_back_a_partially_built_manual_intent(self):
        state = manual_state();state['observation_context'] = None;before = copy.deepcopy(state)
        with self.assertRaisesRegex(TaskError, 'observation context'):
            withdraw(state, 'I', 'TEST.Manual.Activation')
        self.assertEqual(state, before)

    def test_every_manual_nested_receipt_uses_the_observation_that_created_it(self):
        state = manual_state();material = 'TEST.Manual.Activation'
        observe(state, 'INTENT');withdraw(state, 'Unknown', material)
        self.assertEqual(state['bookings']['Unknown']['intent_receipt']['observation']['observation_id'], 'INTENT')
        observe(state, 'UNCERTAIN');ledger.mark_unknown(state, ACTOR, 'Unknown', 'no acknowledgement')
        observe(state, 'ABSENT');ledger.not_performed(state, ACTOR, 'Unknown', 'observed no withdrawal')
        self.assertEqual(state['bookings']['Unknown']['uncertainty']['observation']['observation_id'], 'UNCERTAIN')
        self.assertEqual(state['bookings']['Unknown']['nonperformance']['observation']['observation_id'], 'ABSENT')
        observe(state, 'SECOND_INTENT');withdraw(state, 'Use', material)
        observe(state, 'PERFORMED_UNKNOWN_AMOUNT')
        ledger.confirm_effect(state, ACTOR, 'Use', [{'material_id': material, 'quantity': amount(None)}], [], 'performed')
        confirmation = state['bookings']['Use']['confirmation']
        self.assertEqual(confirmation['observation']['observation_id'], 'PERFORMED_UNKNOWN_AMOUNT')
        observe(state, 'QUANTITY');ledger.resolve_quantity(state, ACTOR, 'Use', material, amount(5), 'measured')
        resolution = state['bookings']['Use']['quantity_resolutions'][material]
        self.assertEqual(resolution['receipt']['observation']['observation_id'], 'QUANTITY')
        self.assertEqual(resolution['observation']['observation_id'], 'QUANTITY')
        observe(state, 'RETAIN');ledger.set_disposition(state, ACTOR, material, 'retained', 'retain')
        observe(state, 'MEASURE')
        ledger.record_measurement(state, ACTOR, material, 'M', 'concentration', amount(2, 'ng/uL'), 'observation')
        self.assertEqual(state['inventory']['materials'][material]['disposition_confirmation']['observation']['observation_id'], 'RETAIN')
        self.assertEqual(state['inventory']['materials'][material]['measurements']['M']['observation']['observation_id'], 'MEASURE')
        observe(state, 'CONSUME');withdraw(state, 'All', 'TEST.Manual.Stop1', 100)
        ledger.confirm_effect(state, ACTOR, 'All', [{'material_id': 'TEST.Manual.Stop1', 'quantity': amount(100)}], [], 'used')
        self.assertEqual(state['inventory']['materials']['TEST.Manual.Stop1']['disposition_confirmation']['evidence'], 'test_fixture')
        self.assertTrue(ledger.audit(state))

    def test_receipt_idempotency_does_not_include_later_recording_time(self):
        state = manual_state();material = 'TEST.Manual.Activation'
        withdraw(state, 'I', material);observe(state, 'CONFIRM')
        actual = [{'material_id': material, 'quantity': amount(5)}]
        ledger.confirm_effect(state, ACTOR, 'I', actual, [], 'done')
        state['logical_time_s'] = 999
        state['clock']['later_capture'] = '2026-11-12T10:00:00Z'
        before = copy.deepcopy(state)
        self.assertIs(ledger.confirm_effect(state, ACTOR, 'I', actual, [], 'done'), False)
        self.assertEqual(state, before)
        observe(state, 'DIFFERENT_OBSERVATION')
        with self.assertRaisesRegex(TaskError, 'Conflicting repeated'):
            ledger.confirm_effect(state, ACTOR, 'I', actual, [], 'done')

    def test_protective_three_preserves_unknown_activation_and_separate_stop_receipts(self):
        state = manual_state();withdraw(state, 'Activation', 'TEST.Manual.Activation')
        observe(state, 'ACTIVATION_UNKNOWN');ledger.mark_unknown(state, ACTOR, 'Activation', 'uncertain')
        activation = copy.deepcopy(state['bookings']['Activation'])
        for index in [1, 2]:
            observe(state, f'STOP{index}_INTENT')
            ledger.begin_protective_stop(state, ACTOR, f'Stop{index}', f'TEST.Manual.Reaction{index}',
                                         f'TEST.Manual.Stop{index}', amount(30))
            observe(state, f'STOP{index}_UNKNOWN')
            ledger.mark_protective_unknown(state, ACTOR, f'Stop{index}', 'uncertain stop')
        self.assertEqual(state['bookings']['Activation'], activation)
        self.assertEqual(state['pending_operation'], {'intent_id': 'Activation'})
        observe(state, 'STOP2_PERFORMED')
        ledger.confirm_protective_stop(state, ACTOR, 'Stop2',
            [{'material_id': 'TEST.Manual.Stop2', 'quantity': amount(30)}], 'observed dose')
        self.assertEqual(ledger.remaining(state, 'TEST.Manual.Stop2')['value'], 70)
        self.assertEqual(state['bookings']['Stop2']['confirmation']['observation']['observation_id'], 'STOP2_PERFORMED')
        self.assertEqual(state['bookings']['Activation'], activation)
        self.assertTrue(ledger.audit(state))


class ManualCorePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='material-v3-');self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name) / 'manual.sqlite3');self.addCleanup(self.journal.close)

    def create(self, identity, state, **options):
        self.journal.create(identity, state, immutable_definition=True,
                            material_allocations=state['definition']['material_allocations'], **options)

    def test_closed_pair_three_is_readable_but_cannot_mix_or_downgrade(self):
        state = manual_state();self.create('TEST.Manual', state)
        self.assertEqual(self.journal.state('TEST.Manual')[0], state)
        self.assertEqual(len(self.journal.audit_material_allocations()), 6)
        for version in [1, 2, 4]:
            changed = copy.deepcopy(state);changed['format'] = 'solidcraftbot.material-workflow-state/' + str(version)
            changed['definition']['format'] = 'solidcraftbot.material-workflow-definition/' + str(version)
            with self.subTest(version=version), self.assertRaises(TaskError):
                self.journal.append('TEST.Manual', 1, 'switch', {}, changed)
        for state_version, definition_version in [(1, 3), (3, 2), (3, 1), (4, 4)]:
            changed = manual_state('TEST.Mix')
            changed['format'] = 'solidcraftbot.material-workflow-state/' + str(state_version)
            changed['definition']['format'] = 'solidcraftbot.material-workflow-definition/' + str(definition_version)
            with self.subTest(pair=(state_version, definition_version)), self.assertRaises(TaskError):
                self.create('TEST.Invalid', changed)
        self.assertEqual(self.journal.get_current('TEST.Manual')[1], 1)

    def test_factory_requires_explicit_manual_fields_and_preserves_initial_none_context(self):
        class Manual(MaterialWorkflow):
            STATE_FORMAT = 'solidcraftbot.material-workflow-state/3'
        state = manual_state()
        for extra in [None, {}, {'clock': {}}, {'observation_context': None},
                      {'clock': {}, 'observation_context': None, 'resources': []}]:
            with self.subTest(extra=extra), self.assertRaises(TaskError):
                Manual._create_definition(self.journal, state['definition'], 'TEST.Bad', extra_state=extra)
        flow = Manual._create_definition(self.journal, state['definition'], 'TEST.Factory',
            extra_state={'clock': {}, 'observation_context': None, 'protective_operations': {}})
        self.assertIsNone(flow.state['observation_context'])
        with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
            MaterialWorkflow(self.journal, flow.run_id, None)

    def test_hooks_refresh_before_deadline_and_preserve_rejected_observation_provenance(self):
        class Manual(MaterialWorkflow):
            STATE_FORMAT = 'solidcraftbot.material-workflow-state/3'
            def _before_transition(self, state):
                state['logical_time_s'] += 2
                state['observation_context'] = context('TEST.CurrentObservation')
            def _event_evidence(self, state, command, actor_id, data):
                return evidence.provenance(state)
        state = manual_state()
        flow = Manual._create_definition(self.journal, state['definition'], 'TEST.Hooks',
            extra_state={'clock': {}, 'observation_context': None, 'protective_operations': {}})
        with self.assertRaises(ObservationError):
            flow.act('accept_inventory', ACTOR, observations=[])
        event = self.journal.history(flow.run_id)[-1]
        self.assertEqual(event['kind'], 'observation_rejected')
        self.assertEqual(event['state']['logical_time_s'], 2)
        self.assertEqual(event['payload']['evidence'], 'test_fixture')
        self.assertEqual(event['payload']['observation']['observation_id'], 'TEST.CurrentObservation')
        self.assertEqual(event['state']['observation_context'], context('TEST.CurrentObservation'))

    def test_inventory_confirmation_uses_manual_context_without_synthetic_relabeling(self):
        class Manual(MaterialWorkflow):
            STATE_FORMAT = 'solidcraftbot.material-workflow-state/3'
        state = manual_state()
        flow = Manual._create_definition(self.journal, state['definition'], 'TEST.Inventory',
            extra_state={'clock': {}, 'observation_context': context('INVENTORY'), 'protective_operations': {}})
        # Call the shared pure handler on a detached proposal, not an E4 runtime.
        proposal = flow.state
        flow._accept_inventory(proposal, ACTOR, flow.inventory_observations())
        receipt = proposal['inventory_confirmation']
        self.assertEqual(receipt['evidence'], 'test_fixture')
        self.assertEqual(receipt['observation']['observation_id'], 'INVENTORY')

    def test_after_transition_records_only_accepted_or_rejected_handler_commits(self):
        class Hooked(MaterialWorkflow):
            STATE_FORMAT = 'solidcraftbot.material-workflow-state/3'
            STEPS = ('accepted', 'rejected', 'unchanged')
            RECOVERY_COMMANDS = MaterialWorkflow.RECOVERY_COMMANDS | set(STEPS)
            observation_id = 'FIRST'
            def _before_transition(self, state):
                state['observation_context'] = context(self.observation_id)
                state['logical_time_s'] += 2
            def _event_evidence(self, state, command, actor_id, data):
                return evidence.provenance(state)
            def _after_transition(self, state, command, actor_id, data, *, rejected=False):
                state['observations'][self.observation_id] = 'rejected' if rejected else 'accepted'
            def _accepted(self, state, actor_id):
                state['test_counter'] += 1
            def _rejected(self, state, actor_id):
                raise ObservationError('TEST rejected observation')
            def _unchanged(self, state, actor_id):
                return False
        state = manual_state()
        flow = Hooked._create_definition(self.journal, state['definition'], 'TEST.AfterHook',
            extra_state={'clock': {}, 'observation_context': None, 'protective_operations': {},
                         'observations': {}, 'test_counter': 0})
        flow.act('accepted', ACTOR)
        self.assertEqual(flow.state['observations'], {'FIRST': 'accepted'})
        flow.observation_id = 'REJECTED'
        with self.assertRaises(ObservationError):flow.act('rejected', ACTOR)
        self.assertEqual(flow.state['observations']['REJECTED'], 'rejected')
        count = len(self.journal.history(flow.run_id))
        flow.observation_id = 'UNCHANGED';flow.act('unchanged', ACTOR)
        self.assertEqual(len(self.journal.history(flow.run_id)), count)
        self.assertNotIn('UNCHANGED', flow.state['observations'])
        current, revision = self.journal.get_current(flow.run_id)
        current.update(recovery_required=None, deadline_s=current['logical_time_s'] + 1)
        self.journal.append(flow.run_id, revision, 'TEST.set_deadline', {}, current)
        flow.observation_id = 'DEADLINE_ONLY';flow.act('check_deadline', ACTOR)
        self.assertEqual(self.journal.history(flow.run_id)[-1]['kind'], 'deadline_exceeded')
        self.assertNotIn('DEADLINE_ONLY', flow.state['observations'])

    def test_initial_artifacts_commit_with_the_manual_introduction(self):
        state = manual_state();originals = {digest(data): data for data in [b'TEST SOP bytes', b'TEST approval bytes']}
        self.create('TEST.Artifacts', state, initial_artifacts=originals)
        for checksum, data in originals.items():self.assertEqual(self.journal.artifact(checksum), data)
        self.assertEqual(self.journal.get_current('TEST.Artifacts')[1], 1)
        self.assertEqual(len(self.journal.audit_material_allocations()), 6)

    def test_initial_artifact_bad_hash_and_partial_create_failure_roll_everything_back(self):
        state = manual_state();data = b'TEST original source'
        for originals in [{'0' * 64: data}, {digest(data): 'not bytes'}]:
            with self.subTest(originals=originals), self.assertRaises(TaskError):
                self.create('TEST.BadArtifact', state, initial_artifacts=originals)
            self.assertEqual(self.journal.connection.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
        original = self.journal._event
        def fail_after_event(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('TEST failure after source retention and event')
        with patch.object(self.journal, '_event', side_effect=fail_after_event), self.assertRaises(OSError):
            self.create('TEST.Failed', state, initial_artifacts={digest(data): data})
        self.assertEqual(self.journal.connection.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
        self.assertEqual(self.journal.owners(), {})
        with self.assertRaises(TaskError):self.journal.artifact(digest(data))
        self.assertEqual(self.journal.audit_material_allocations(), {})

    def test_journal_failure_cannot_commit_manual_receipt_or_source_context(self):
        state = manual_state();self.create('TEST.Run', state)
        before, revision = self.journal.get_current('TEST.Run')
        proposal = copy.deepcopy(before);observe(proposal, 'NEW_CONTEXT')
        withdraw(proposal, 'I', 'TEST.Manual.Activation')
        with patch.object(self.journal, '_event', side_effect=OSError('TEST rollback')), self.assertRaises(OSError):
            self.journal.append('TEST.Run', revision, 'manual_intent', {'observation': context('NEW_CONTEXT')}, proposal)
        self.assertEqual(self.journal.get_current('TEST.Run'), (before, revision))
        self.assertNotIn('I', self.journal.state('TEST.Run')[0]['bookings'])


if __name__ == '__main__':
    unittest.main()
