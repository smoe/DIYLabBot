"""Closed material versions and independent protective stop bookkeeping."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal, TaskError, digest, encoded
from manual_workflow import ObservationError
import material_ledger as ledger
from material_workflow import MaterialWorkflow

ACTOR = 'SYN.Protective.Operator'


def amount(value, unit='uL'):
    return {'value': value, 'unit': unit}


def fixture(version=2, prefix='SYN.Protective'):
    initial = [{'id': prefix + '.' + name, 'kind': 'reagent', 'vessel_id': prefix + '.' + name + '.Tube',
                'quantity': amount(100), 'origin_id': prefix + '.Issue'}
               for name in ['Activation', 'Stop1', 'Stop2']]
    vessels = [{'id': identity, 'location': {'kind': 'rack', 'rack_id': prefix + '.Rack', 'place_id': 'P%02d' % index}}
               for index, identity in enumerate([item['vessel_id'] for item in initial] +
                    [prefix + '.Reaction1', prefix + '.Reaction2'], 1)]
    definition = {'format': 'solidcraftbot.material-workflow-definition/' + str(version),
                  'domain': 'cutrun', 'profile': {'parameters': {'task_deadline_s': 3600}},
                  'clock_mode': 'synthetic_events/1', 'initial_materials': initial, 'initial_vessels': vessels,
                  'material_allocations': [{'material_id': item['id'], 'vessel_id': item['vessel_id'],
                                            'declaration_sha256': digest(encoded(item).encode())} for item in initial]}
    state = {'format': 'solidcraftbot.material-workflow-state/' + str(version), 'definition': definition,
             'resources': ['vessel:' + item['id'] for item in vessels], 'logical_time_s': 0.0,
             'inventory': ledger.initial_inventory(initial, vessels), 'bookings': {}, 'pending_operation': None,
             'recovery_required': None, 'workspace_clear': False}
    if version == 2:
        definition['protective_stop_bindings'] = {prefix + '.Reaction1': prefix + '.Stop1',
                                                 prefix + '.Reaction2': prefix + '.Stop2'}
        state['protective_operations'] = {}
    return state


def activation_unknown(state, material='SYN.Protective.Activation'):
    ledger.begin_effect(state, ACTOR, 'SYN.ActivationIntent', 'withdrawal',
        [{'material_id': material, 'quantity': amount(5), 'consume_all': False}], [], 'synthetic_activation')
    ledger.mark_unknown(state, ACTOR, 'SYN.ActivationIntent', 'Synthetic missing activation acknowledgement')


def stop(state, number=1, intent=None, quantity=30):
    return ledger.begin_protective_stop(state, ACTOR, intent or f'SYN.StopIntent{number}',
        f'SYN.Protective.Reaction{number}', f'SYN.Protective.Stop{number}', amount(quantity))


class MaterialVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='material-v2-')
        self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name) / 'shared.sqlite3')
        self.addCleanup(self.journal.close)

    def create(self, run, state):
        self.journal.create(run, state, immutable_definition=True,
                            material_allocations=state['definition']['material_allocations'])

    def test_both_closed_version_pairs_are_stored_read_and_audited_together(self):
        for version in [1, 2]:
            state = fixture(version, f'SYN.Version{version}')
            self.create(f'SYN.Run{version}', state)
            self.assertEqual(self.journal.state(f'SYN.Run{version}')[0], state)
            self.assertTrue(ledger.audit(state))
        self.assertEqual(len(self.journal.audit_material_allocations()), 12)
        self.assertNotIn('protective_operations', self.journal.state('SYN.Run1')[0])

    def test_mixed_definition_state_pairs_and_unknown_versions_cannot_be_created(self):
        for state_version, definition_version in [(1, 2), (2, 1), (3, 3)]:
            state = fixture(state_version)
            state['definition']['format'] = 'solidcraftbot.material-workflow-definition/' + str(definition_version)
            with self.subTest(pair=(state_version, definition_version)), self.assertRaises(TaskError):
                self.create('SYN.Invalid', state)
            self.assertEqual(self.journal.connection.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
        state = fixture(3)
        with self.assertRaisesRegex(TaskError, 'Unsupported material workflow state version'):
            self.journal.create('SYN.Invalid', state)

    def test_append_cannot_switch_or_downgrade_a_material_version(self):
        for version, other in [(1, 2), (2, 1)]:
            run = f'SYN.Run{version}';self.create(run, fixture(version, run))
            before, revision = self.journal.get_current(run)
            changed = copy.deepcopy(before)
            changed['format'] = 'solidcraftbot.material-workflow-state/' + str(other)
            changed['definition']['format'] = 'solidcraftbot.material-workflow-definition/' + str(other)
            changed['resources'] = []
            with self.subTest(version=version), self.assertRaisesRegex(TaskError, 'version cannot change'):
                self.journal.append(run, revision, 'switch', {}, changed)
            self.assertEqual(self.journal.get_current(run), (before, revision))
            changed = copy.deepcopy(before);changed['format'] = 'solidcraftbot.material-workflow-state/3'
            with self.assertRaises(TaskError):self.journal.append(run, revision, 'unknown', {}, changed)

    def test_permanent_allocations_are_exclusive_in_both_version_directions(self):
        for owner_version, target_version in [(1, 2), (2, 1)]:
            prefix = f'SYN.Shared{owner_version}'
            run = prefix + '.Owner';self.create(run, fixture(owner_version, prefix))
            state, revision = self.journal.get_current(run);state['resources'] = []
            self.journal.append(run, revision, 'released', {}, state)
            target = fixture(target_version, prefix);target['resources'] = []
            with self.subTest(owner=owner_version), self.assertRaisesRegex(TaskError, 'permanently allocated'):
                self.create(prefix + '.Other', target)
            self.assertIsNone(self.journal.connection.execute('SELECT id FROM runs WHERE id=?', (prefix + '.Other',)).fetchone())

    def test_shared_factory_preserves_e2_format_and_rejects_e2_writer_for_v2(self):
        class V2Workflow(MaterialWorkflow):
            STATE_FORMAT = 'solidcraftbot.material-workflow-state/2'
        one, two = fixture(1, 'SYN.Factory1'), fixture(2, 'SYN.Factory2')
        old = MaterialWorkflow._create_definition(self.journal, one['definition'], 'SYN.FactoryRun1')
        newer = V2Workflow._create_definition(self.journal, two['definition'], 'SYN.FactoryRun2',
            extra_state={'protective_operations': {}, 'process': {'phase': 'prepared'}})
        self.assertNotIn('protective_operations', old.state)
        self.assertEqual(newer.state['process'], {'phase': 'prepared'})
        with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
            MaterialWorkflow.open(self.journal, newer.run_id)
        with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
            MaterialWorkflow(self.journal, newer.run_id, None)
        with self.assertRaisesRegex(TaskError, 'Wrong workflow format'):
            V2Workflow.open(self.journal, old.run_id)
        with self.assertRaisesRegex(TaskError, 'versions must match'):
            MaterialWorkflow._create_definition(self.journal, two['definition'], 'SYN.WrongFactory')
        with self.assertRaisesRegex(TaskError, 'cannot override common fields'):
            V2Workflow._create_definition(self.journal, two['definition'], 'SYN.Override', extra_state={'resources': []})

    def test_journal_failure_rolls_back_protected_booking_and_preserves_unknown_activation(self):
        state = fixture();activation_unknown(state)
        self.create('SYN.Run', state)
        before, revision = self.journal.get_current('SYN.Run');claims = self.journal.audit_material_allocations()
        proposed = copy.deepcopy(before);stop(proposed)
        original = self.journal._event
        def fail_after_event(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('Synthetic event failure')
        with patch.object(self.journal, '_event', side_effect=fail_after_event), self.assertRaises(OSError):
            self.journal.append('SYN.Run', revision, 'protective_intent', {}, proposed, artifact=b'SYN.Stop')
        self.assertEqual(self.journal.get_current('SYN.Run'), (before, revision))
        self.assertEqual(self.journal.audit_material_allocations(), claims)
        with self.assertRaises(TaskError):self.journal.artifact(digest(b'SYN.Stop'))


class ProtectiveLedgerTests(unittest.TestCase):
    def test_unknown_activation_and_two_independent_unknown_stops_share_one_balance(self):
        state = fixture();activation_unknown(state)
        normal = copy.deepcopy(state['bookings']['SYN.ActivationIntent'])
        pending = copy.deepcopy(state['pending_operation'])
        for number in [1, 2]:
            stop(state, number)
            ledger.mark_protective_unknown(state, ACTOR, f'SYN.StopIntent{number}', 'Synthetic missing stop acknowledgement')
            self.assertEqual(state['pending_operation'], pending)
            self.assertEqual(state['bookings']['SYN.ActivationIntent'], normal)
        self.assertEqual(state['protective_operations'], {'SYN.Protective.Reaction1': 'SYN.StopIntent1',
                                                          'SYN.Protective.Reaction2': 'SYN.StopIntent2'})
        for name in ['Activation', 'Stop1', 'Stop2']:
            self.assertIsNone(ledger.remaining(state, 'SYN.Protective.' + name)['value'])
        self.assertTrue(all(not booking['actual_inputs'] for booking in state['bookings'].values()))
        ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent2',
            [{'material_id': 'SYN.Protective.Stop2', 'quantity': amount(30)}], 'Synthetic confirmed stop dose')
        self.assertEqual(ledger.remaining(state, 'SYN.Protective.Stop2')['value'], 70)
        self.assertEqual(state['bookings']['SYN.ActivationIntent'], normal)
        self.assertEqual(state['pending_operation'], pending)
        ledger.resolve_protective_stop(state, ACTOR, 'SYN.StopIntent1', 'not_performed', None,
                                      'Explicit synthetic no-stop observation')
        self.assertEqual(ledger.remaining(state, 'SYN.Protective.Stop1')['value'], 100)
        self.assertEqual(state['bookings']['SYN.ActivationIntent'], normal)
        self.assertTrue(ledger.audit(state))

    def test_protective_confirmation_and_nonperformance_are_idempotent(self):
        state = fixture();stop(state)
        actual = [{'material_id': 'SYN.Protective.Stop1', 'quantity': amount(30)}]
        ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent1', actual, 'Synthetic receipt')
        before = copy.deepcopy(state)
        self.assertIs(ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent1', actual, 'Synthetic receipt'), False)
        self.assertIs(stop(state), False);self.assertEqual(state, before)
        with self.assertRaises(TaskError):
            ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent1', actual, 'Changed receipt')
        stop(state, 2)
        ledger.resolve_protective_stop(state, ACTOR, 'SYN.StopIntent2', 'not_performed', None, 'No stop')
        self.assertIs(ledger.resolve_protective_stop(state, ACTOR, 'SYN.StopIntent2', 'not_performed', None, 'No stop'), False)
        self.assertEqual(ledger.remaining(state, 'SYN.Protective.Stop2')['value'], 100)
        self.assertTrue(ledger.audit(state))

    def test_wrong_aliquot_second_lifetime_intent_and_reused_normal_intent_are_rejected(self):
        state = fixture();before = copy.deepcopy(state)
        with self.assertRaises(TaskError):
            ledger.begin_protective_stop(state, ACTOR, 'Wrong', 'SYN.Protective.Reaction1', 'SYN.Protective.Stop2', amount(30))
        self.assertEqual(state, before)
        stop(state)
        ledger.resolve_protective_stop(state, ACTOR, 'SYN.StopIntent1', 'not_performed', None, 'No stop')
        with self.assertRaisesRegex(TaskError, 'lifetime'):
            stop(state, intent='SYN.NewAttempt')
        normal = fixture()
        ledger.begin_effect(normal, ACTOR, 'Existing', 'withdrawal',
            [{'material_id': 'SYN.Protective.Stop1', 'quantity': amount(1), 'consume_all': False}], [], 'protective_stop')
        ledger.confirm_effect(normal, ACTOR, 'Existing',
            [{'material_id': 'SYN.Protective.Stop1', 'quantity': amount(1)}], [], 'Synthetic generic withdrawal')
        with self.assertRaisesRegex(TaskError, 'already used'):
            stop(normal, intent='Existing')

    def test_pending_input_sets_must_be_disjoint_but_independent_stop_remains_available(self):
        state = fixture();activation_unknown(state, material='SYN.Protective.Stop1')
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(TaskError, 'disjoint'):stop(state)
        self.assertEqual(state, before)
        stop(state, 2);self.assertTrue(ledger.audit(state))
        state['definition']['protective_stop_bindings']['SYN.Protective.Reaction1'] = 'SYN.Protective.Stop2'
        with self.assertRaisesRegex(TaskError, 'disjoint'):
            ledger.begin_protective_stop(state, ACTOR, 'Other', 'SYN.Protective.Reaction1', 'SYN.Protective.Stop2', amount(30))

    def test_dose_bounds_units_and_confirmed_overdraw_preserve_pending_state(self):
        state = fixture()
        for value in [amount(101), amount(1, 'mg'), amount(True), amount(float('nan'))]:
            before = copy.deepcopy(state)
            with self.subTest(quantity=value), self.assertRaises(TaskError):
                ledger.begin_protective_stop(state, ACTOR, 'Bad', 'SYN.Protective.Reaction1', 'SYN.Protective.Stop1', value)
            self.assertEqual(state, before)
        stop(state);before = copy.deepcopy(state)
        with self.assertRaises(ObservationError):
            ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent1',
                [{'material_id': 'SYN.Protective.Stop1', 'quantity': amount(101)}], 'Invalid dose')
        self.assertEqual(state, before)

    def test_unknown_stop_does_not_allow_normal_work_disposition_or_measurement(self):
        state = fixture();stop(state)
        ledger.mark_protective_unknown(state, ACTOR, 'SYN.StopIntent1', 'Uncertain stop')
        before = copy.deepcopy(state)
        calls = [lambda: ledger.begin_effect(state, ACTOR, 'NewNormal', 'withdrawal',
            [{'material_id': 'SYN.Protective.Activation', 'quantity': amount(1), 'consume_all': False}], [], 'normal'),
            lambda: ledger.set_disposition(state, ACTOR, 'SYN.Protective.Activation', 'retained', 'retain'),
            lambda: ledger.record_measurement(state, ACTOR, 'SYN.Protective.Activation', 'Measurement',
                                               'concentration', amount(2, 'ng/uL'), 'Synthetic measurement')]
        for call in calls:
            with self.assertRaisesRegex(TaskError, 'protective'):call()
            self.assertEqual(state, before)

    def test_known_stop_with_unknown_quantity_is_not_a_zero_debit(self):
        state = fixture();stop(state)
        ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent1',
            [{'material_id': 'SYN.Protective.Stop1', 'quantity': amount(None)}], 'Known synthetic delivery, quantity unknown')
        self.assertEqual(state['bookings']['SYN.StopIntent1']['outcome'], 'performed')
        self.assertEqual(ledger.remaining(state, 'SYN.Protective.Stop1')['knowledge'], 'confirmed_quantity_unknown')
        self.assertIsNone(ledger.remaining(state, 'SYN.Protective.Stop1')['value'])
        ledger.resolve_quantity(state, ACTOR, 'SYN.StopIntent1', 'SYN.Protective.Stop1', amount(30), 'Synthetic measured amount')
        self.assertEqual(ledger.remaining(state, 'SYN.Protective.Stop1')['value'], 70)
        self.assertTrue(ledger.audit(state))

    def test_atomic_proposal_failure_cannot_leave_an_alias_or_change_normal_pending(self):
        state = fixture();activation_unknown(state);before = copy.deepcopy(state)
        original = ledger._begin_effect
        def fail_after_begin(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Synthetic failure after proposal mutation')
        with patch.object(ledger, '_begin_effect', side_effect=fail_after_begin), self.assertRaises(RuntimeError):
            stop(state)
        self.assertEqual(state, before)
        stop(state);before = copy.deepcopy(state)
        original_confirm = ledger.confirm_effect
        def fail_after_confirm(*args, **kwargs):
            original_confirm(*args, **kwargs)
            raise RuntimeError('Synthetic failure after debit')
        with patch.object(ledger, 'confirm_effect', side_effect=fail_after_confirm), self.assertRaises(RuntimeError):
            ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent1',
                [{'material_id': 'SYN.Protective.Stop1', 'quantity': amount(30)}], 'Synthetic stop')
        self.assertEqual(state, before)

    def test_audit_rejects_removed_closed_reference_wrong_binding_and_pending_overlap(self):
        state = fixture();activation_unknown(state);stop(state)
        ledger.confirm_protective_stop(state, ACTOR, 'SYN.StopIntent1',
            [{'material_id': 'SYN.Protective.Stop1', 'quantity': amount(30)}], 'Synthetic stop')
        removed = copy.deepcopy(state);removed['protective_operations'].clear()
        with self.assertRaisesRegex(TaskError, 'cannot be removed'):ledger.audit(removed)
        with self.assertRaises(TaskError):stop(removed, intent='SecondAfterDeletingReference')
        wrong = copy.deepcopy(state);wrong['bookings']['SYN.StopIntent1']['request']['inputs'][0]['material_id'] = 'SYN.Protective.Stop2'
        wrong['bookings']['SYN.StopIntent1']['request_sha256'] = digest(encoded(wrong['bookings']['SYN.StopIntent1']['request']).encode())
        with self.assertRaisesRegex(TaskError, 'bound issued aliquot'):ledger.audit(wrong)
        pending = fixture();activation_unknown(pending);stop(pending)
        booking = pending['bookings']['SYN.ActivationIntent'];booking['request']['inputs'][0]['material_id'] = 'SYN.Protective.Stop1'
        booking['request_sha256'] = digest(encoded(booking['request']).encode())
        with self.assertRaisesRegex(TaskError, 'disjoint'):ledger.audit(pending)

    def test_v1_remains_single_pending_and_cannot_use_protective_apis(self):
        state = fixture(1);activation_unknown(state)
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(TaskError, 'version-2'):stop(state)
        with self.assertRaisesRegex(TaskError, 'pending material operation'):
            ledger.begin_effect(state, ACTOR, 'Second', 'withdrawal',
                [{'material_id': 'SYN.Protective.Stop2', 'quantity': amount(30), 'consume_all': False}], [], 'normal')
        self.assertEqual(state, before);self.assertTrue(ledger.audit(state))
        self.assertNotIn('protective_operations', state)


if __name__ == '__main__':
    unittest.main()
