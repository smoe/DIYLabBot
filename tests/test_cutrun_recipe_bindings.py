"""Canonical working-reagent preparation fixtures; no laboratory execution."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import cutrun_recipe_bindings as bindings
import material_ledger as ledger
from manual_tasks import Journal, TaskError, digest, encoded
from cutrun_manual_workflow import CutRunManualWorkflow


ACTOR = 'Test.Recipe.Operator'


def amount(value, unit='uL'):
    return {'value': value, 'unit': unit}


def fixture():
    materials = [{'id': 'Test.' + name, 'kind': kind, 'vessel_id': 'Test.' + name + '.Tube',
                  'quantity': amount(value, unit), 'origin_id': 'Test.Issue.' + name}
                 for name, kind, value, unit in [('StockA', 'reagent', 1000, 'uL'),
                     ('StockB', 'reagent', 1000, 'uL'), ('Activation', 'reagent', 100, 'uL'),
                     ('Sample', 'sample', 1000, 'cells')]]
    vessels = [{'id': identity, 'location': {'kind': 'rack', 'rack_id': 'Test.Rack', 'place_id': 'P' + str(index)}}
               for index, identity in enumerate([item['vessel_id'] for item in materials]
                   + ['Test.StopMix.Tube', 'Test.WashWaste.Tube'], 1)]
    protocol = {'reagent_roles': {
        'stock.a': {'kind': 'stock', 'components': []},
        'stock.b': {'kind': 'stock', 'components': []},
        'working.stop': {'kind': 'working', 'components': ['stock.a', 'stock.b']}},
        'stage_steps': {'S03': [{'id': 'S03.stock_wash', 'target_role': 'stock.a'}]}}
    profile = {'roles': {}}
    for name, identity in [('stock.a', 'StockA'), ('stock.b', 'StockB')]:
        profile['roles'][name] = {'mode': 'issued', 'material_id': 'Test.' + identity,
            'vessel_id': 'Test.' + identity + '.Tube', 'lot_ref': 'Test.Lot.' + identity,
            'preparation_ref': None, 'evidence_ref': 'Test.Decision', 'components': {},
            'output_quantity': amount(None)}
    profile['roles']['working.stop'] = {'mode': 'prepared', 'material_id': 'Test.StopMix',
        'vessel_id': 'Test.StopMix.Tube', 'lot_ref': None, 'preparation_ref': 'Test.StopRecipe',
        'evidence_ref': 'Test.Decision', 'components': {'stock.a': amount(10), 'stock.b': amount(20)},
        'output_quantity': amount(30)}
    definition = {'format': 'solidcraftbot.material-workflow-definition/3',
        'profile': {'type': bindings.ENGINE}, 'initial_materials': materials, 'initial_vessels': vessels,
        'material_allocations': [{'material_id': item['id'], 'vessel_id': item['vessel_id'],
            'declaration_sha256': digest(encoded(item).encode())} for item in materials if item['kind'] == 'reagent']}
    bindings.augment_definition(definition, protocol, profile, {'Test.Sample.Tube': 'Test.StopMix'})
    state = {'format': 'solidcraftbot.material-workflow-state/3', 'definition': definition,
        'inventory': ledger.initial_inventory(materials, vessels), 'bookings': {}, 'pending_operation': None,
        'protective_operations': {}, 'manual': {'actions': {}}, 'recipe': {'role_materials': {}},
        'logical_time_s': 0, 'recovery_required': None, 'workspace_clear': False,
        'observation_context': {'observation_id': 'Test.Observation', 'source_kind': 'test_fixture',
            'observed_at': None, 'source_ref': 'Test fixture, not laboratory evidence', 'artifact_sha256': None}}
    return state


def begin_preparation(state, intent='Test.Prepare'):
    inputs = [{'material_id': identity, 'quantity': amount(value), 'consume_all': False}
              for identity, value in [('Test.StockA', 10), ('Test.StockB', 20)]]
    outputs = [{'material_id': 'Test.StopMix', 'kind': 'intermediate',
                'vessel_id': 'Test.StopMix.Tube', 'role': 'working_reagent'}]
    ledger.begin_effect(state, ACTOR, intent, 'transformation', inputs, outputs, 'recipe_preparation:working.stop')
    state['manual']['actions'][intent] = {'operation': 'recipe_preparation', 'recipe_role': 'working.stop',
                                        'component_materials': {'stock.a': 'Test.StockA', 'stock.b': 'Test.StockB'}}


def prepare(state, *, actual_a=10, actual_b=20, output=30, intent='Test.Prepare'):
    begin_preparation(state, intent)
    ledger.confirm_effect(state, ACTOR, intent,
        [{'material_id': identity, 'quantity': amount(value)} for identity, value in
         [('Test.StockA', actual_a), ('Test.StockB', actual_b)]],
        [{'material_id': 'Test.StopMix', 'quantity': amount(output)}], 'Explicit test preparation observation')
    return intent


class RecipeBindingTests(unittest.TestCase):
    def test_future_mix_is_allocated_but_not_introduced_or_ready(self):
        state = fixture()
        self.assertNotIn('Test.StopMix', state['inventory']['materials'])
        allocation = next(item for item in state['definition']['material_allocations'] if item['material_id'] == 'Test.StopMix')
        self.assertEqual(allocation['vessel_id'], 'Test.StopMix.Tube')
        self.assertFalse(bindings.protected_ready(state, 'Test.Sample.Tube'))
        self.assertTrue(ledger.audit(state))

    def test_future_alias_allocation_cannot_be_reused_by_a_second_run(self):
        state = fixture();state['resources'] = ['vessel:' + name for name in state['inventory']['vessels']]
        state['resources'] += ['material:' + name for name in state['inventory']['materials']]
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / 'journal.sqlite3') as journal:
            journal.create('Test.One', state, immutable_definition=True,
                           material_allocations=state['definition']['material_allocations'])
            self.assertIn('material:Test.StopMix', journal.audit_material_allocations())
            with self.assertRaises(TaskError):
                journal.create('Test.Two', state, immutable_definition=True,
                               material_allocations=state['definition']['material_allocations'])

    def test_factory_accepts_only_actual_issued_or_explicit_future_recipe_outputs(self):
        state = fixture();profile = state['definition']['recipe_profile'];inventory = state['inventory']
        item = {'stop_material_id': 'Test.StopMix'}
        self.assertEqual(bindings.validate_reagent_binding(inventory, profile, item, 'stop_material_id'), 'working.stop')
        with self.assertRaises(TaskError):
            CutRunManualWorkflow._validate_reagent_binding(inventory, None, 'Test.Reaction', item, 'stop_material_id')
        with self.assertRaises(TaskError):
            bindings.validate_reagent_binding(inventory, profile, {'stop_material_id': 'Test.Missing'}, 'stop_material_id')
        open_profile = {'roles': {'working.unbound': {'mode': None, 'material_id': None}}}
        self.assertIsNone(bindings.validate_reagent_binding(inventory, open_profile,
                         {'stop_material_id': 'Test.Activation'}, 'stop_material_id'))

    def test_preparation_uses_one_canonical_introduction_and_stock_consumption(self):
        state = fixture();prepare(state)
        self.assertTrue(bindings.reagent_ready(state, 'working.stop'))
        self.assertTrue(bindings.protected_ready(state, 'Test.Sample.Tube'))
        self.assertEqual(ledger.remaining(state, 'Test.StockA')['value'], 990)
        self.assertEqual(ledger.remaining(state, 'Test.StockB')['value'], 980)
        self.assertEqual(state['inventory']['materials']['Test.StopMix']['kind'], 'intermediate')
        self.assertEqual(state['inventory']['materials']['Test.StopMix']['parents'], ['Test.StockA', 'Test.StockB'])
        self.assertTrue(ledger.audit(state))

    def test_open_prepared_quantities_and_evidence_remain_archivable_without_readiness(self):
        state = fixture();definition = copy.deepcopy(state['definition'])
        definition['material_allocations'] = definition['material_allocations'][:-1]
        profile = copy.deepcopy(definition['recipe_profile'])
        role = profile['roles']['working.stop']
        role.update(preparation_ref=None, evidence_ref=None, output_quantity=amount(None))
        role['components']['stock.a'] = amount(None)
        bindings.augment_definition(definition, definition['recipe_protocol'], profile,
                                     {'Test.Sample.Tube': 'Test.StopMix'})
        state['definition'] = definition
        self.assertFalse(bindings.protected_ready(state, 'Test.Sample.Tube'))
        self.assertTrue(ledger.audit(state))
        self.assertEqual(bindings.validate_reagent_binding(state['inventory'], profile,
            {'stop_material_id': 'Test.StopMix'}, 'stop_material_id'), 'working.stop')

    def test_protective_stop_can_be_booked_with_an_unrelated_pending_effect(self):
        state = fixture();prepare(state)
        ledger.begin_effect(state, ACTOR, 'Test.Ordinary', 'withdrawal',
            [{'material_id': 'Test.Sample', 'quantity': amount(1, 'cells'), 'consume_all': False}], [], 'test ordinary')
        ledger.begin_protective_stop(state, ACTOR, 'Test.Stop', 'Test.Sample.Tube', 'Test.StopMix', amount(5))
        actual = [{'material_id': 'Test.StopMix', 'quantity': amount(5)}]
        ledger.confirm_protective_stop(state, ACTOR, 'Test.Stop', actual, 'Test stop observed')
        self.assertEqual(state['pending_operation'], {'intent_id': 'Test.Ordinary'})
        self.assertEqual(ledger.remaining(state, 'Test.StopMix')['value'], 25)
        self.assertIs(ledger.confirm_protective_stop(state, ACTOR, 'Test.Stop', actual, 'Test stop observed'), False)
        self.assertEqual(ledger.remaining(state, 'Test.StockA')['value'], 990)
        self.assertTrue(ledger.audit(state))

    def test_unknown_or_mismatched_preparation_remains_readable_but_not_ready(self):
        for actual_a, output in [(None, 30), (11, 30), (10, None), (10, 29)]:
            with self.subTest(actual_a=actual_a, output=output):
                state = fixture();prepare(state, actual_a=actual_a, output=output)
                self.assertFalse(bindings.reagent_ready(state, 'working.stop'))
                self.assertTrue(ledger.audit(state))

    def test_a_quantity_reconciliation_does_not_debit_the_stock_again(self):
        state = fixture();prepare(state, actual_a=None)
        ledger.resolve_quantity(state, ACTOR, 'Test.Prepare', 'Test.StockA', amount(10), 'Test measured missing component')
        self.assertTrue(bindings.reagent_ready(state, 'working.stop'))
        self.assertEqual(ledger.remaining(state, 'Test.StockA')['value'], 990)

    def test_preparation_conformance_survives_exhaustion_but_not_unknown_source_provenance(self):
        state = fixture();prepare(state)
        ledger.begin_protective_stop(state, ACTOR, 'Test.Stop', 'Test.Sample.Tube', 'Test.StopMix', amount(30))
        ledger.confirm_protective_stop(state, ACTOR, 'Test.Stop',
            [{'material_id': 'Test.StopMix', 'quantity': amount(30)}], 'Test entire observed dose')
        self.assertTrue(bindings.preparation_conformant(state, 'working.stop'))
        self.assertFalse(bindings.reagent_ready(state, 'working.stop'))
        state['definition']['recipe_profile']['roles']['stock.a']['lot_ref'] = None
        self.assertFalse(bindings.preparation_conformant(state, 'working.stop'))

    def test_issued_stock_with_open_lot_or_evidence_is_not_a_qualified_dose_source(self):
        for field in ('lot_ref', 'evidence_ref'):
            with self.subTest(field=field):
                state = fixture()
                state['definition']['recipe_profile']['roles']['stock.a'][field] = None
                self.assertFalse(bindings.reagent_ready(state, 'stock.a'))
                self.assertTrue(ledger.audit(state))

    def test_an_unknown_preparation_never_makes_a_future_stop_source_ready(self):
        state = fixture()
        ledger.begin_effect(state, ACTOR, 'Test.PendingPrep', 'transformation',
            [{'material_id': 'Test.StockA', 'quantity': amount(10), 'consume_all': False},
             {'material_id': 'Test.StockB', 'quantity': amount(20), 'consume_all': False}],
            [{'material_id': 'Test.StopMix', 'kind': 'intermediate', 'vessel_id': 'Test.StopMix.Tube', 'role': 'working_reagent'}],
            'recipe_preparation:working.stop')
        ledger.mark_unknown(state, ACTOR, 'Test.PendingPrep', 'Test lost receipt')
        self.assertFalse(bindings.protected_ready(state, 'Test.Sample.Tube'))
        with self.assertRaises(TaskError):
            ledger.begin_protective_stop(state, ACTOR, 'Test.Stop', 'Test.Sample.Tube', 'Test.StopMix', amount(5))
        self.assertTrue(ledger.audit(state))

    def test_changed_declaration_missing_allocation_and_wrong_preparation_role_are_rejected(self):
        for change in ['declaration', 'allocation', 'action', 'parents', 'output_quantity']:
            with self.subTest(change=change):
                state = fixture();prepare(state)
                if change == 'declaration':state['definition']['recipe_profile']['roles']['working.stop']['components']['stock.a'] = amount(11)
                elif change == 'allocation':state['definition']['material_allocations'] = state['definition']['material_allocations'][:-1]
                elif change == 'action':state['manual']['actions']['Test.Prepare']['recipe_role'] = 'stock.a'
                elif change == 'parents':state['inventory']['materials']['Test.StopMix']['parents'] = ['Test.StockA']
                else:state['inventory']['materials']['Test.StopMix']['initial_quantity'] = amount(31)
                with self.assertRaises(TaskError):bindings.protected_ready(state, 'Test.Sample.Tube')

    def test_old_capture_engine_cannot_opt_into_a_prepared_protective_source(self):
        state = fixture();prepare(state)
        state['definition']['profile']['type'] = 'cutrun_manual_capture/1'
        with self.assertRaises(TaskError):ledger.audit(state)

    def test_initial_materials_cannot_be_relabelled_as_prepared_mixtures(self):
        state = fixture();profile = copy.deepcopy(state['definition']['recipe_profile'])
        profile['roles']['working.stop'].update(material_id='Test.StockA', vessel_id='Test.StockA.Tube')
        with self.assertRaises(TaskError):
            bindings.validate_reagent_binding(state['inventory'], profile,
                                             {'stop_material_id': 'Test.StockA'}, 'stop_material_id')

    def test_later_observed_mix_yield_is_canonical_and_preserves_original_confirmation(self):
        state = fixture();prepare(state, output=None)
        original = copy.deepcopy(state['bookings']['Test.Prepare']['confirmation'])
        bindings.resolve_prepared_output(state, ACTOR, 'Test.Prepare', amount(30), 'Test later volume observation')
        booking = state['bookings']['Test.Prepare']
        self.assertEqual(booking['confirmation'], original)
        self.assertEqual(booking['confirmation']['actual_outputs'][0]['quantity'], amount(None))
        self.assertEqual(booking['actual_outputs'][0]['quantity'], amount(30))
        self.assertEqual(booking['output_quantity_resolution']['receipt']['evidence'], 'test_fixture')
        self.assertTrue(bindings.preparation_conformant(state, 'working.stop'))
        self.assertEqual(ledger.remaining(state, 'Test.StockA')['value'], 990)
        self.assertIs(bindings.resolve_prepared_output(state, ACTOR, 'Test.Prepare', amount(30),
                                                       'Test later volume observation'), False)
        with self.assertRaises(TaskError):
            bindings.resolve_prepared_output(state, ACTOR, 'Test.Prepare', amount(31), 'Test changed result')

    def test_mix_yield_reconciliation_rejects_pending_usage_or_less_than_confirmed_consumption(self):
        from manual_workflow import ObservationError
        state = fixture();prepare(state, output=None)
        ledger.begin_protective_stop(state, ACTOR, 'Test.Stop', 'Test.Sample.Tube', 'Test.StopMix', amount(5))
        before = copy.deepcopy(state)
        with self.assertRaises(TaskError):
            bindings.resolve_prepared_output(state, ACTOR, 'Test.Prepare', amount(30), 'Test unresolved usage')
        self.assertEqual(state, before)
        ledger.confirm_protective_stop(state, ACTOR, 'Test.Stop',
            [{'material_id': 'Test.StopMix', 'quantity': amount(5)}], 'Test actual external use')
        before = copy.deepcopy(state)
        with self.assertRaises(ObservationError):
            bindings.resolve_prepared_output(state, ACTOR, 'Test.Prepare', amount(3), 'Test contradictory yield')
        self.assertEqual(state, before)
        bindings.resolve_prepared_output(state, ACTOR, 'Test.Prepare', amount(30), 'Test observed sufficient yield')
        self.assertEqual(ledger.remaining(state, 'Test.StopMix')['value'], 25)

    def test_a_known_yield_or_initial_aliquot_cannot_be_changed_by_mix_reconciliation(self):
        state = fixture();prepare(state)
        with self.assertRaises(TaskError):
            bindings.resolve_prepared_output(state, ACTOR, 'Test.Prepare', amount(31), 'Test rewrite denied')
        ledger.begin_effect(state, ACTOR, 'Test.WithdrawStock', 'withdrawal',
            [{'material_id': 'Test.StockA', 'quantity': amount(1), 'consume_all': False}], [], 'Test stock use')
        ledger.confirm_effect(state, ACTOR, 'Test.WithdrawStock',
            [{'material_id': 'Test.StockA', 'quantity': amount(1)}], [], 'Test stock observed')
        with self.assertRaises(TaskError):
            bindings.resolve_prepared_output(state, ACTOR, 'Test.WithdrawStock', amount(500), 'Test initial reset denied')

    def test_explicit_nonperformance_releases_only_the_same_allocated_preparation_output_for_retry(self):
        state = fixture();begin_preparation(state, 'Test.Absent')
        ledger.not_performed(state, ACTOR, 'Test.Absent', 'Test observed no preparation')
        prepare(state, intent='Test.Retry')
        self.assertEqual(state['bookings']['Test.Absent']['outcome'], 'not_performed')
        self.assertEqual(state['bookings']['Test.Retry']['outcome'], 'performed')
        self.assertEqual(ledger.remaining(state, 'Test.StockA')['value'], 990)
        self.assertTrue(ledger.audit(state))

    def test_unknown_attempt_and_other_engines_do_not_release_output_identity(self):
        state = fixture();begin_preparation(state, 'Test.Unknown')
        ledger.mark_unknown(state, ACTOR, 'Test.Unknown', 'Test lost observation')
        with self.assertRaises(TaskError):begin_preparation(state, 'Test.BlindRetry')
        state = fixture();begin_preparation(state, 'Test.Absent')
        ledger.not_performed(state, ACTOR, 'Test.Absent', 'Test no effect observed')
        state['definition']['profile']['type'] = 'cutrun_manual_capture/1'
        state['definition']['protective_stop_bindings'] = {'Test.Sample.Tube': 'Test.Activation'}
        with self.assertRaises(TaskError):begin_preparation(state, 'Test.OldEngineRetry')

    def test_missing_feature_or_wrong_material_version_is_not_a_recipe_opt_in(self):
        for change in ['feature', 'state_version', 'definition_version']:
            with self.subTest(change=change):
                state = fixture()
                if change == 'feature':del state['definition']['recipe_protective_bindings']
                elif change == 'state_version':state['format'] = 'solidcraftbot.material-workflow-state/2'
                else:state['definition']['format'] = 'solidcraftbot.material-workflow-definition/2'
                with self.assertRaises(TaskError):bindings.protected_ready(state, 'Test.Sample.Tube')

    def test_role_alias_needs_a_canonical_retained_recipe_effect(self):
        state = fixture()
        inputs = [{'material_id': 'Test.StockA', 'quantity': amount(1000), 'consume_all': True}]
        outputs = [{'material_id': 'Test.WashedA', 'kind': 'intermediate', 'vessel_id': 'Test.StockA.Tube', 'role': 'washed_stock'}]
        ledger.begin_effect(state, ACTOR, 'Test.Wash', 'transformation', inputs, outputs, 'recipe_operation:S03.stock_wash:add')
        state['manual']['actions']['Test.Wash'] = {'operation': 'recipe_material', 'recipe_target_role': 'stock.a',
            'recipe_step_id': 'S03.stock_wash', 'retained_material_id': 'Test.WashedA'}
        ledger.confirm_effect(state, ACTOR, 'Test.Wash', [{'material_id': 'Test.StockA', 'quantity': amount(1000)}],
            [{'material_id': 'Test.WashedA', 'quantity': amount(500)}], 'Test retained stock')
        state['recipe']['role_materials']['stock.a'] = 'Test.WashedA'
        self.assertEqual(bindings.resolve_role_material(state, 'stock.a'), 'Test.WashedA')
        self.assertTrue(bindings.reagent_ready(state, 'stock.a'))
        state['manual']['actions']['Test.Wash']['retained_material_id'] = 'Test.WashWaste'
        with self.assertRaises(TaskError):bindings.resolve_role_material(state, 'stock.a')

    def test_preparation_consumes_the_proved_current_stock_fraction_without_resetting_stock(self):
        state = fixture()
        ledger.begin_effect(state, ACTOR, 'Test.Wash', 'transformation',
            [{'material_id': 'Test.StockA', 'quantity': amount(1000), 'consume_all': True}],
            [{'material_id': 'Test.WashedA', 'kind': 'intermediate', 'vessel_id': 'Test.StockA.Tube', 'role': 'washed_stock'}],
            'recipe_operation:S03.stock_wash:remove')
        state['manual']['actions']['Test.Wash'] = {'operation': 'recipe_material', 'recipe_target_role': 'stock.a',
            'recipe_step_id': 'S03.stock_wash', 'retained_material_id': 'Test.WashedA'}
        ledger.confirm_effect(state, ACTOR, 'Test.Wash', [{'material_id': 'Test.StockA', 'quantity': amount(1000)}],
            [{'material_id': 'Test.WashedA', 'quantity': amount(500)}], 'Test observed retained stock fraction')
        state['recipe']['role_materials']['stock.a'] = 'Test.WashedA'
        ledger.begin_effect(state, ACTOR, 'Test.Prepare', 'transformation',
            [{'material_id': 'Test.WashedA', 'quantity': amount(10), 'consume_all': False},
             {'material_id': 'Test.StockB', 'quantity': amount(20), 'consume_all': False}],
            [{'material_id': 'Test.StopMix', 'kind': 'intermediate', 'vessel_id': 'Test.StopMix.Tube', 'role': 'working_reagent'}],
            'recipe_preparation:working.stop')
        state['manual']['actions']['Test.Prepare'] = {'operation': 'recipe_preparation', 'recipe_role': 'working.stop',
            'component_materials': {'stock.a': 'Test.WashedA', 'stock.b': 'Test.StockB'}}
        ledger.confirm_effect(state, ACTOR, 'Test.Prepare',
            [{'material_id': 'Test.WashedA', 'quantity': amount(10)}, {'material_id': 'Test.StockB', 'quantity': amount(20)}],
            [{'material_id': 'Test.StopMix', 'quantity': amount(30)}], 'Test observed working mixture')
        self.assertTrue(bindings.protected_ready(state, 'Test.Sample.Tube'))
        self.assertEqual(ledger.remaining(state, 'Test.StockA')['value'], 0)
        self.assertEqual(ledger.remaining(state, 'Test.WashedA')['value'], 490)
        self.assertEqual(ledger.remaining(state, 'Test.StockB')['value'], 980)
        self.assertTrue(ledger.audit(state))

    def test_wrong_wash_dose_stays_unqualified_in_retained_stock_and_derived_preparation(self):
        state = fixture()
        ledger.begin_effect(state, ACTOR, 'Test.BadWash', 'transformation',
            [{'material_id': 'Test.StockA', 'quantity': amount(1000), 'consume_all': True},
             {'material_id': 'Test.StockB', 'quantity': amount(5), 'consume_all': False}],
            [{'material_id': 'Test.WashedA', 'kind': 'intermediate', 'vessel_id': 'Test.StockA.Tube', 'role': 'washed_stock'}],
            'recipe_operation:S03.stock_wash:add')
        state['manual']['actions']['Test.BadWash'] = {'operation': 'recipe_material', 'recipe_target_role': 'stock.a',
            'recipe_step_id': 'S03.stock_wash', 'retained_material_id': 'Test.WashedA'}
        ledger.confirm_effect(state, ACTOR, 'Test.BadWash',
            [{'material_id': 'Test.StockA', 'quantity': amount(1000)}, {'material_id': 'Test.StockB', 'quantity': amount(6)}],
            [{'material_id': 'Test.WashedA', 'quantity': amount(1006)}], 'Test wrong actual wash dose')
        state['recipe']['role_materials']['stock.a'] = 'Test.WashedA'
        self.assertEqual(bindings.resolve_role_material(state, 'stock.a'), 'Test.WashedA')
        self.assertFalse(bindings.reagent_ready(state, 'stock.a'))
        self.assertFalse(bindings.preparation_conformant(state, 'stock.a'))
        # Preserve an actually performed downstream preparation, rather than
        # making the contradictory physical effect unreadable or discarding it.
        ledger.begin_effect(state, ACTOR, 'Test.ExternalPrep', 'transformation',
            [{'material_id': 'Test.WashedA', 'quantity': amount(10), 'consume_all': False},
             {'material_id': 'Test.StockB', 'quantity': amount(20), 'consume_all': False}],
            [{'material_id': 'Test.StopMix', 'kind': 'intermediate', 'vessel_id': 'Test.StopMix.Tube', 'role': 'working_reagent'}],
            'recipe_preparation:working.stop')
        state['manual']['actions']['Test.ExternalPrep'] = {'operation': 'recipe_preparation', 'recipe_role': 'working.stop',
            'component_materials': {'stock.a': 'Test.WashedA', 'stock.b': 'Test.StockB'}}
        ledger.confirm_effect(state, ACTOR, 'Test.ExternalPrep',
            [{'material_id': 'Test.WashedA', 'quantity': amount(10)}, {'material_id': 'Test.StockB', 'quantity': amount(20)}],
            [{'material_id': 'Test.StopMix', 'quantity': amount(30)}], 'Test actual downstream preparation')
        self.assertFalse(bindings.preparation_conformant(state, 'working.stop'))
        self.assertFalse(bindings.protected_ready(state, 'Test.Sample.Tube'))
        state['recipe']['role_materials']['stock.a'] = 'Test.StockA'
        self.assertFalse(bindings.preparation_conformant(state, 'working.stop'))
        self.assertTrue(ledger.audit(state))
        ledger.begin_protective_stop(state, ACTOR, 'Test.ActualStop', 'Test.Sample.Tube', 'Test.StopMix', amount(5))
        ledger.confirm_protective_stop(state, ACTOR, 'Test.ActualStop',
            [{'material_id': 'Test.StopMix', 'quantity': amount(5)}], 'Test actual protective effect remains archivable')
        self.assertTrue(ledger.audit(state))


if __name__ == '__main__':
    unittest.main()
