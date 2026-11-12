"""The common material root retains products and journals typed effects once."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from manual_tasks import Journal, TaskError
from manual_workflow import ObservationError
import cutrun_preparation
import extraction_preparation
import material_ledger as ledger
from material_workflow import MaterialWorkflow

ACTOR = 'SYN.Material.Operator'


def amount(value, unit='uL'):
    return {'value': value, 'unit': unit}


def preparation_seeds(domain, suffix='TEST'):
    plan = (cutrun_preparation.compile_plan() if domain == 'cutrun'
            else extraction_preparation.compile_plan())
    inputs, products, vessel_ids = [], {}, set()
    if domain == 'cutrun':
        for branch in plan['branches']:
            inputs.append({'id': branch['input_material_id'],
                'kind': 'sample' if branch['role'] == 'reference' else 'control',
                'vessel_id': branch['vessels']['input'], 'quantity': amount(100000, 'cells'),
                'origin_id': branch['id']})
            products[branch['input_material_id']] = (branch['product_material_id'], branch['vessels']['product'])
            vessel_ids.update(branch['vessels'].values())
    else:
        for pair in plan['sample_pairs']:
            for process in pair['processes'].values():
                edge = process['lineage']
                inputs.append({'id': edge['input_id'], 'kind': 'sample',
                    'vessel_id': edge['input_vessel_id'], 'quantity': amount(1, 'mg'),
                    'origin_id': edge['origin_id']})
                products[edge['input_id']] = (edge['product_id'], edge['product_vessel_id'])
                vessel_ids.update(item['instance_id'] for item in process['item_bindings'].values())
    reagent_id, reagent_vessel = f'SYN.Reagent.{suffix}', f'SYN.ReagentTube.{suffix}'
    inputs.append({'id': reagent_id, 'kind': 'reagent', 'vessel_id': reagent_vessel,
                   'quantity': amount(100), 'origin_id': 'SYN.IssuedAliquot'})
    vessel_ids.update((reagent_vessel, f'SYN.ExtraTube.{suffix}'))
    vessels = [{'id': identity, 'location': {'kind': 'rack', 'rack_id': f'SYN.MaterialRack.{suffix}',
                 'place_id': f'P{index:03d}'}} for index, identity in enumerate(sorted(vessel_ids), 1)]
    return plan, inputs, vessels, products, reagent_id


class MaterialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.journal = Journal(self.folder / 'shared.sqlite3')
        self.addCleanup(self.journal.close)
        self.serial = 0

    def create(self, domain='cutrun', ready=True, mutate=None):
        self.serial += 1
        suffix = f'T{self.serial}'
        plan, materials, vessels, products, reagent_id = preparation_seeds(domain, suffix)
        if mutate:
            mutate(materials, vessels)
        flow = MaterialWorkflow.create(self.journal, domain, materials=materials, vessels=vessels,
                                       run_id=f'SYN.MATERIAL.{suffix}')
        if ready:
            flow.act('accept_inventory', ACTOR, observations=self.observations(flow))
            flow.act('workspace_clear', ACTOR, confirmed=True)
            flow.act('claim', ACTOR)
        return flow, materials, vessels, products, reagent_id

    @staticmethod
    def observations(flow):
        state = flow.state
        return [{'vessel_id': identity, 'location': copy.deepcopy(vessel['location']),
                 'material_ids': sorted(material_id for material_id, material in state['inventory']['materials'].items()
                                        if material['vessel_id'] == identity)}
                for identity, vessel in state['inventory']['vessels'].items()]

    def transform(self, flow, source, product, vessel, *, intent='SYN.Transform',
                  actual_source=None, actual_product=50, extras=()):
        material = flow.state['inventory']['materials'][source]
        quantity = copy.deepcopy(material['initial_quantity'])
        outputs = [{'material_id': product, 'kind': 'product', 'vessel_id': vessel, 'role': 'dna_product'}, *extras]
        flow.act('begin_effect', ACTOR, intent_id=intent, kind='transformation',
                 inputs=[{'material_id': source, 'quantity': quantity, 'consume_all': True}],
                 outputs=outputs, purpose='synthetic_material_transformation')
        receipts = [{'material_id': product, 'quantity': amount(actual_product)}]
        receipts += [{'material_id': item['material_id'], 'quantity': amount(None)} for item in extras]
        actual = copy.deepcopy(quantity) if actual_source is None else actual_source
        flow.act('confirm_effect', ACTOR, intent_id=intent,
                 actual_inputs=[{'material_id': source, 'quantity': actual}],
                 actual_outputs=receipts, reason='Explicit synthetic effect and quantities')
        return outputs, actual, receipts

    def withdraw(self, flow, source, quantity=2, *, intent='SYN.QC', purpose='qc'):
        flow.act('begin_effect', ACTOR, intent_id=intent, kind='withdrawal',
                 inputs=[{'material_id': source, 'quantity': amount(quantity), 'consume_all': False}],
                 outputs=[], purpose=purpose)
        return {'intent_id': intent, 'actual_inputs': [{'material_id': source, 'quantity': amount(quantity)}],
                'actual_outputs': [], 'reason': 'Explicit synthetic withdrawal'}

    def confirm(self, flow, receipt):
        return flow.act('confirm_effect', ACTOR, **receipt)

    def test_both_preparations_use_one_material_state_contract(self):
        for domain in ['cutrun', 'extraction']:
            with self.subTest(domain=domain):
                flow, inputs, vessels, products, reagent = self.create(domain)
                state = flow.state
                self.assertEqual(state['format'], 'solidcraftbot.material-workflow-state/1')
                self.assertNotIn('samples', state)
                self.assertNotIn('derived_vessels', state)
                self.assertEqual(set(state['inventory']['materials']), {item['id'] for item in inputs})
                self.assertEqual(set(state['inventory']['vessels']), {item['id'] for item in vessels})
                self.assertEqual(state['definition']['preparation_plan']['execution_ready'], False)
                source = next(iter(products)); product, vessel = products[source]
                self.transform(flow, source, product, vessel)
                self.assertEqual(ledger.remaining(flow.state, product)['value'], 50)
                self.assertEqual(flow.state['inventory']['materials'][source]['disposition'], 'consumed')

    def test_one_to_many_lineage_retains_product_and_unknown_byproduct_quantity(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = next(iter(products)); product, vessel = products[source]
        extra = {'material_id': 'SYN.Byproduct', 'kind': 'byproduct',
                 'vessel_id': 'SYN.ExtraTube.T1', 'role': 'retained_side_fraction'}
        self.transform(flow, source, product, vessel, extras=[extra])
        state = flow.state
        self.assertEqual(state['inventory']['materials'][product]['parents'], [source])
        self.assertEqual(state['inventory']['materials']['SYN.Byproduct']['parents'], [source])
        self.assertIsNone(ledger.remaining(state, 'SYN.Byproduct')['value'])
        self.assertEqual(ledger.remaining(state, 'SYN.Byproduct')['knowledge'], 'initial_unknown')
        flow.act('record_measurement', ACTOR, material_id='SYN.Byproduct', measurement_id='SYN.SideFraction.Concentration',
                 kind='concentration', quantity=amount(5, 'ng/uL'), reason='Synthetic concentration with unknown volume')
        self.assertIsNone(ledger.remaining(flow.state, 'SYN.Byproduct')['value'])
        flow.act('set_disposition', ACTOR, material_id=product, disposition='retained', reason='Keep purified DNA')
        flow.act('set_disposition', ACTOR, material_id='SYN.Byproduct', disposition='quarantined', reason='Retain for review')
        self.assertNotEqual(flow.state['inventory']['materials'][product]['disposition'], 'discarded')

    def test_material_change_in_same_vessel_does_not_create_another_vessel(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = inputs[0]['id']; source_vessel = inputs[0]['vessel_id']
        before_vessels = set(flow.state['inventory']['vessels'])
        self.transform(flow, source, 'SYN.SameVessel.Product', source_vessel)
        state = flow.state
        self.assertEqual(set(state['inventory']['vessels']), before_vessels)
        self.assertIsNone(state['inventory']['materials'][source]['vessel_id'])
        self.assertEqual(state['inventory']['materials']['SYN.SameVessel.Product']['vessel_id'], source_vessel)

    def test_qc_debits_product_once_and_never_debits_the_consumed_input_again(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = next(iter(products)); product, vessel = products[source]
        self.transform(flow, source, product, vessel)
        before_source = ledger.remaining(flow.state, source)
        receipt = self.withdraw(flow, product)
        self.confirm(flow, receipt)
        count = len(self.journal.history(flow.run_id))
        self.confirm(flow, receipt)
        self.assertEqual(len(self.journal.history(flow.run_id)), count)
        self.assertEqual(ledger.remaining(flow.state, product)['value'], 48)
        self.assertEqual(ledger.remaining(flow.state, source), before_source)
        changed = copy.deepcopy(receipt); changed['actual_inputs'][0]['quantity']['value'] = 3
        with self.assertRaises(TaskError):
            self.confirm(flow, changed)
        self.assertEqual(ledger.remaining(flow.state, product)['value'], 48)

    def test_reagent_consumption_is_booked_against_the_issued_aliquot_once(self):
        flow, inputs, vessels, products, reagent = self.create()
        receipt = self.withdraw(flow, reagent, quantity=7, intent='SYN.ReagentUse', purpose='process_reagent')
        self.confirm(flow, receipt)
        self.confirm(flow, receipt)
        self.assertEqual(ledger.remaining(flow.state, reagent)['value'], 93)
        self.assertTrue(self.journal.audit_material_allocations())

    def test_unknown_initial_quantity_stays_unknown_after_confirmed_known_withdrawal(self):
        def unknown(materials, vessels):
            materials[-1]['quantity'] = amount(None)
        flow, inputs, vessels, products, reagent = self.create(mutate=unknown)
        receipt = self.withdraw(flow, reagent)
        self.confirm(flow, receipt)
        projection = ledger.remaining(flow.state, reagent)
        self.assertIsNone(projection['value'])
        self.assertEqual(projection['knowledge'], 'initial_unknown')

    def test_known_units_are_not_converted_between_cells_mass_and_volume(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = inputs[0]['id']
        for quantity in [amount(1), amount(1, 'mg'), amount(True, 'cells'), amount(1.5, 'cells')]:
            with self.subTest(quantity=quantity), self.assertRaises(TaskError):
                flow.act('begin_effect', ACTOR, intent_id='SYN.BadUnits', kind='withdrawal',
                         inputs=[{'material_id': source, 'quantity': quantity, 'consume_all': False}],
                         outputs=[], purpose='invalid_dimension')
        self.assertIsNone(flow.state['pending_operation'])
        self.assertEqual(ledger.remaining(flow.state, source)['value'], 100000)

    def test_nonfinite_intent_quantities_are_domain_errors_without_partial_bookings(self):
        flow, inputs, vessels, products, reagent = self.create()
        before = flow.state
        for value in [float('nan'), float('inf'), -float('inf')]:
            with self.subTest(value=value), self.assertRaises(TaskError):
                flow.act('begin_effect', ACTOR, intent_id='SYN.Nonfinite', kind='withdrawal',
                         inputs=[{'material_id': reagent, 'quantity': amount(value), 'consume_all': False}],
                         outputs=[], purpose='invalid_nonfinite_quantity')
        self.assertEqual(flow.state, before)

    def test_declared_preparation_product_cannot_be_created_from_the_wrong_input(self):
        flow, inputs, vessels, products, reagent = self.create()
        source, wrong_source = list(products)[:2]
        product, vessel = products[source]
        before = flow.state
        with self.assertRaises(TaskError):
            flow.act('begin_effect', ACTOR, intent_id='SYN.WrongParent', kind='transformation',
                     inputs=[{'material_id': wrong_source, 'quantity': amount(100000, 'cells'), 'consume_all': True}],
                     outputs=[{'material_id': product, 'kind': 'product', 'vessel_id': vessel, 'role': 'dna_product'}],
                     purpose='wrong_preparation_parent')
        self.assertEqual(flow.state, before)

    def test_audit_rejects_reset_initial_quantity_and_disappearing_material_or_vessel(self):
        flow, inputs, vessels, products, reagent = self.create()
        before = flow.state
        for mutation in ['quantity_reset', 'missing_input', 'missing_vessel']:
            state = copy.deepcopy(before)
            if mutation == 'quantity_reset':
                state['inventory']['materials'][reagent]['initial_quantity']['value'] = 200
            elif mutation == 'missing_input':
                del state['inventory']['materials'][inputs[0]['id']]
            else:
                del state['inventory']['vessels']['SYN.ExtraTube.T1']
            with self.subTest(mutation=mutation), self.assertRaises(TaskError):
                ledger.audit(state)
        self.assertEqual(flow.state, before)

    def test_concentration_is_metadata_and_cannot_be_used_as_a_consumable_balance(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = next(iter(products)); product, vessel = products[source]
        self.transform(flow, source, product, vessel)
        flow.act('record_measurement', ACTOR, material_id=product, measurement_id='SYN.Concentration',
                 kind='concentration', quantity=amount(5, 'ng/uL'), reason='Synthetic analytical observation')
        self.assertEqual(ledger.remaining(flow.state, product)['value'], 50)
        with self.assertRaises(TaskError):
            flow.act('begin_effect', ACTOR, intent_id='SYN.BadConcentrationDebit', kind='withdrawal',
                     inputs=[{'material_id': product, 'quantity': amount(2, 'ng/uL'), 'consume_all': False}],
                     outputs=[], purpose='invalid_concentration_debit')

    def test_mass_measurement_is_invalidated_at_intent_and_not_silently_restored(self):
        flow, inputs, vessels, products, reagent = self.create()
        measurement = {'material_id': reagent, 'measurement_id': 'SYN.TotalMass',
                       'kind': 'total_vessel_mass', 'quantity': amount(2, 'g'),
                       'reason': 'Explicit synthetic total vessel mass'}
        flow.act('record_measurement', ACTOR, **measurement)
        self.assertTrue(flow.report()['measurement_validity'][reagent]['SYN.TotalMass'])
        stored = copy.deepcopy(flow.state['inventory']['materials'][reagent]['measurements']['SYN.TotalMass'])
        self.withdraw(flow, reagent, intent='SYN.MassInvalidatingIntent')
        self.assertFalse(flow.report()['measurement_validity'][reagent]['SYN.TotalMass'])
        self.assertEqual(flow.state['inventory']['materials'][reagent]['measurements']['SYN.TotalMass'], stored)
        flow.act('not_performed', ACTOR, intent_id='SYN.MassInvalidatingIntent',
                 reason='Explicit synthetic observation of no withdrawal')
        self.assertEqual(ledger.remaining(flow.state, reagent)['value'], 100)
        self.assertFalse(flow.report()['measurement_validity'][reagent]['SYN.TotalMass'])
        revision = len(self.journal.history(flow.run_id))
        flow.act('record_measurement', ACTOR, **measurement)
        self.assertEqual(len(self.journal.history(flow.run_id)), revision)
        self.assertFalse(flow.report()['measurement_validity'][reagent]['SYN.TotalMass'])

    def test_confirmed_over_withdrawal_holds_the_run_and_preserves_intent_and_resources(self):
        flow, inputs, vessels, products, reagent = self.create()
        receipt = self.withdraw(flow, reagent, quantity=2)
        receipt['actual_inputs'][0]['quantity']['value'] = 101
        resources = copy.deepcopy(self.journal.owners())
        with self.assertRaises(ObservationError):
            self.confirm(flow, receipt)
        self.assertIsNotNone(flow.state['pending_operation'])
        self.assertTrue(flow.state['recovery_required'])
        self.assertEqual(self.journal.owners(), resources)
        self.assertEqual(flow.state['bookings']['SYN.QC']['outcome'], 'intent')

    def test_confirmation_failure_rolls_back_event_children_debit_and_artifact(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = next(iter(products)); product, vessel = products[source]
        flow.act('begin_effect', ACTOR, intent_id='SYN.Rollback', kind='transformation',
                 inputs=[{'material_id': source, 'quantity': amount(100000, 'cells'), 'consume_all': True}],
                 outputs=[{'material_id': product, 'kind': 'product', 'vessel_id': vessel, 'role': 'dna_product'}],
                 purpose='synthetic_material_transformation')
        before = flow.state
        count = len(self.journal.history(flow.run_id))
        resources = copy.deepcopy(self.journal.owners())
        artifacts = self.journal.connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]
        original = self.journal._event
        def fail_after_event(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Synthetic crash after event insert')
        with patch.object(self.journal, '_event', side_effect=fail_after_event), self.assertRaises(RuntimeError):
            flow.act('confirm_effect', ACTOR, intent_id='SYN.Rollback',
                     actual_inputs=[{'material_id': source, 'quantity': amount(100000, 'cells')}],
                     actual_outputs=[{'material_id': product, 'quantity': amount(50)}],
                     reason='Synthetic confirmation', artifact=b'SYNTHETIC EVIDENCE')
        self.assertEqual(flow.state, before)
        self.assertEqual(len(self.journal.history(flow.run_id)), count)
        self.assertEqual(self.journal.owners(), resources)
        self.assertEqual(self.journal.connection.execute('SELECT count(*) FROM artifacts').fetchone()[0], artifacts)

    def test_resume_requires_explicit_inventory_reconciliation_and_fences_the_old_session(self):
        flow, inputs, vessels, products, reagent = self.create()
        resumed = MaterialWorkflow.open(self.journal, flow.run_id, resume=True)
        with self.assertRaises(TaskError):
            flow.act('advance_time', ACTOR, seconds=1)
        self.assertTrue(resumed.state['recovery_required'])
        with self.assertRaises(TaskError):
            resumed.act('advance_time', ACTOR, seconds=1)
        resumed.act('reconcile', ACTOR, observations=self.observations(resumed), workspace_clear=False)
        self.assertIsNone(resumed.state['recovery_required'])
        self.assertEqual(ledger.remaining(resumed.state, reagent)['value'], 100)

    def test_resume_before_initial_inventory_can_reconcile_and_then_accept_the_fixture(self):
        flow, inputs, vessels, products, reagent = self.create(ready=False)
        self.assertEqual(flow.state['status'], 'created')
        flow.close()
        resumed = MaterialWorkflow.open(self.journal, flow.run_id, resume=True)
        self.assertTrue(resumed.state['recovery_required'])
        resumed.act('reconcile', ACTOR, observations=self.observations(resumed), workspace_clear=False)
        resumed.act('accept_inventory', ACTOR, observations=self.observations(resumed))
        resumed.act('workspace_clear', ACTOR, confirmed=True)
        resumed.act('claim', ACTOR)
        self.assertEqual(resumed.state['status'], 'working')
        self.assertEqual(ledger.remaining(resumed.state, reagent)['value'], 100)

    def test_cancel_before_claim_retains_material_and_releases_only_after_inventory_confirmation(self):
        for phase in ['created', 'ready']:
            with self.subTest(phase=phase):
                flow, inputs, vessels, products, reagent = self.create(ready=False)
                if phase == 'ready':
                    flow.act('accept_inventory', ACTOR, observations=self.observations(flow))
                flow.act('cancel', ACTOR, reason='Explicit synthetic cancellation before claim')
                self.assertTrue(flow.state['resources'])
                flow.act('reconcile', ACTOR, observations=self.observations(flow), workspace_clear=False)
                for material_id in flow.state['inventory']['materials']:
                    flow.act('set_disposition', ACTOR, material_id=material_id, disposition='retained',
                             reason='Retain unused material after cancellation')
                flow.act('confirm_inventory', ACTOR, observations=self.observations(flow))
                flow.act('finish_cancel', ACTOR, workspace_clear=True)
                self.assertEqual(flow.state['status'], 'cancelled')
                self.assertEqual(flow.state['resources'], [])
                self.assertEqual(self.journal.owners(), {})

    def test_unknown_effect_holds_until_explicit_outcome_and_never_becomes_zero_consumption(self):
        flow, inputs, vessels, products, reagent = self.create()
        receipt = self.withdraw(flow, reagent, intent='SYN.Uncertain')
        flow.act('mark_unknown', ACTOR, intent_id='SYN.Uncertain', reason='Synthetic lost acknowledgement')
        state = flow.state
        self.assertIsNone(ledger.remaining(state, reagent)['value'])
        self.assertEqual(ledger.remaining(state, reagent)['knowledge'], 'unresolved_operation')
        self.assertEqual(state['bookings']['SYN.Uncertain']['outcome'], 'unknown')
        with self.assertRaises(TaskError):
            flow.act('begin_effect', ACTOR, intent_id='SYN.Retry', kind='withdrawal',
                     inputs=[{'material_id': reagent, 'quantity': amount(2), 'consume_all': False}],
                     outputs=[], purpose='unsafe_blind_retry')
        flow.act('reconcile', ACTOR, observations=self.observations(flow), workspace_clear=False,
                 intent_id='SYN.Uncertain', outcome='unknown', reason='Still no outcome evidence')
        self.assertTrue(flow.state['recovery_required'])
        flow.act('reconcile', ACTOR, observations=self.observations(flow), workspace_clear=False,
                 outcome='performed', **receipt)
        self.assertIsNone(flow.state['pending_operation'])
        self.assertIsNone(flow.state['recovery_required'])
        self.assertEqual(ledger.remaining(flow.state, reagent)['value'], 98)
        self.confirm(flow, receipt)
        self.assertEqual(ledger.remaining(flow.state, reagent)['value'], 98)

    def test_confirmed_not_performed_outcome_keeps_the_initial_quantity(self):
        flow, inputs, vessels, products, reagent = self.create()
        self.withdraw(flow, reagent, intent='SYN.NotPerformed')
        flow.act('mark_unknown', ACTOR, intent_id='SYN.NotPerformed', reason='Uncertain synthetic effect')
        flow.act('reconcile', ACTOR, observations=self.observations(flow), workspace_clear=False,
                 intent_id='SYN.NotPerformed', outcome='not_performed', reason='Explicit no-effect observation')
        self.assertEqual(ledger.remaining(flow.state, reagent)['value'], 100)
        self.assertEqual(flow.state['bookings']['SYN.NotPerformed']['outcome'], 'not_performed')
        self.assertIsNone(flow.state['pending_operation'])

    def test_unknown_transformation_reconciles_observed_children_without_repeating_the_effect(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = next(iter(products)); product, product_vessel = products[source]
        source_vessel = flow.state['inventory']['materials'][source]['vessel_id']
        flow.act('begin_effect', ACTOR, intent_id='SYN.Transform.Uncertain', kind='transformation',
                 inputs=[{'material_id': source, 'quantity': amount(100000, 'cells'), 'consume_all': True}],
                 outputs=[{'material_id': product, 'kind': 'product', 'vessel_id': product_vessel, 'role': 'dna_product'}],
                 purpose='synthetic_material_transformation')
        flow.act('mark_unknown', ACTOR, intent_id='SYN.Transform.Uncertain', reason='Synthetic lost transformation receipt')
        observations = self.observations(flow)
        for observation in observations:
            if observation['vessel_id'] == source_vessel:
                observation['material_ids'] = []
            elif observation['vessel_id'] == product_vessel:
                observation['material_ids'] = [product]
        flow.act('reconcile', ACTOR, observations=observations, workspace_clear=False,
                 intent_id='SYN.Transform.Uncertain', outcome='performed',
                 actual_inputs=[{'material_id': source, 'quantity': amount(100000, 'cells')}],
                 actual_outputs=[{'material_id': product, 'quantity': amount(50)}],
                 reason='Explicit synthetic observed input consumption and product')
        state = flow.state
        self.assertIsNone(state['pending_operation'])
        self.assertIsNone(state['recovery_required'])
        self.assertEqual(state['inventory']['materials'][product]['parents'], [source])
        self.assertEqual(ledger.remaining(state, product)['value'], 50)
        self.assertEqual(ledger.remaining(state, source)['value'], 0)

    def test_invalid_initial_quantities_leave_no_run_or_resource(self):
        for index, quantity in enumerate([amount(True), amount(float('nan')), amount(float('inf')),
                                          amount(-1), amount(2, 'ng/uL')]):
            plan, materials, vessels, products, reagent = preparation_seeds('cutrun', f'INVALID{index}')
            materials[-1]['quantity'] = quantity
            with self.subTest(quantity=quantity), self.assertRaises(TaskError):
                MaterialWorkflow.create(self.journal, 'cutrun', materials=materials, vessels=vessels,
                                        run_id=f'SYN.InvalidMaterial.{index}')
        self.assertEqual(self.journal.connection.execute('SELECT count(*) FROM runs').fetchone()[0], 0)
        self.assertEqual(self.journal.owners(), {})

    def test_known_effect_with_unknown_quantity_is_distinct_and_can_be_resolved_once(self):
        flow, inputs, vessels, products, reagent = self.create()
        receipt = self.withdraw(flow, reagent, intent='SYN.Unquantified')
        receipt['actual_inputs'][0]['quantity']['value'] = None
        self.confirm(flow, receipt)
        projection = ledger.remaining(flow.state, reagent)
        self.assertIsNone(projection['value'])
        self.assertEqual(projection['knowledge'], 'confirmed_quantity_unknown')
        self.assertEqual(flow.state['bookings']['SYN.Unquantified']['outcome'], 'performed')
        self.assertIsNone(flow.state['pending_operation'])
        self.assertEqual(flow.state['inventory']['materials'][reagent]['disposition'], 'quarantined')
        resolution = {'intent_id': 'SYN.Unquantified', 'material_id': reagent,
                      'quantity': amount(2), 'reason': 'Explicit synthetic quantity evidence'}
        before = flow.state
        revision = len(self.journal.history(flow.run_id))
        with self.assertRaises(TaskError):
            flow.act('resolve_quantity', ACTOR, **{**resolution, 'quantity': amount(None)})
        self.assertEqual(flow.state, before)
        self.assertEqual(len(self.journal.history(flow.run_id)), revision)
        flow.act('resolve_quantity', ACTOR, **resolution)
        revision = len(self.journal.history(flow.run_id))
        flow.act('resolve_quantity', ACTOR, **resolution)
        self.assertEqual(len(self.journal.history(flow.run_id)), revision)
        self.assertEqual(ledger.remaining(flow.state, reagent)['value'], 98)
        with self.assertRaises(TaskError):
            flow.act('resolve_quantity', ACTOR, **{**resolution, 'quantity': amount(3)})

    def test_unknown_clarification_cannot_poison_resolution_when_the_initial_quantity_is_unknown(self):
        def unknown(materials, vessels):
            materials[-1]['quantity'] = amount(None)
        flow, inputs, vessels, products, reagent = self.create(mutate=unknown)
        receipt = self.withdraw(flow, reagent, intent='SYN.Unquantified.UnknownInitial')
        receipt['actual_inputs'][0]['quantity']['value'] = None
        self.confirm(flow, receipt)
        resolution = {'intent_id': receipt['intent_id'], 'material_id': reagent,
                      'quantity': amount(None), 'reason': 'Explicit synthetic quantity evidence'}
        before = flow.state
        revision = len(self.journal.history(flow.run_id))
        with self.assertRaises(TaskError):
            flow.act('resolve_quantity', ACTOR, **resolution)
        self.assertEqual(flow.state, before)
        self.assertEqual(len(self.journal.history(flow.run_id)), revision)
        flow.act('resolve_quantity', ACTOR, **{**resolution, 'quantity': amount(3)})
        self.assertEqual(flow.state['bookings'][receipt['intent_id']]['actual_inputs'][0]['quantity'], amount(3))
        self.assertIsNone(ledger.remaining(flow.state, reagent)['value'])
        self.assertEqual(ledger.remaining(flow.state, reagent)['knowledge'], 'initial_unknown')

    def test_completion_retains_products_and_untouched_sources_without_blanket_disposal(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = next(iter(products)); product, vessel = products[source]
        self.transform(flow, source, product, vessel)
        for material_id, material in flow.state['inventory']['materials'].items():
            if material['disposition'] == 'consumed':
                continue
            flow.act('set_disposition', ACTOR, material_id=material_id, disposition='retained',
                     reason='Explicit synthetic retention at confirmed inventory place')
        with self.assertRaises(TaskError):
            flow.act('release', ACTOR, workspace_clear=True)
        flow.act('confirm_inventory', ACTOR, observations=self.observations(flow))
        flow.act('release', ACTOR, workspace_clear=True)
        self.assertEqual(flow.state['status'], 'completed')
        self.assertEqual(flow.state['resources'], [])
        self.assertEqual(flow.state['inventory']['materials'][product]['disposition'], 'retained')
        self.assertEqual(flow.state['inventory']['materials'][source]['disposition'], 'consumed')
        self.assertEqual(self.journal.owners(), {})
        report = flow.report()
        self.assertTrue(report['passed'])
        self.assertFalse(report['hardware_executed'])
        self.assertTrue(self.journal.audit_material_allocations())
        self.assertEqual(MaterialWorkflow.open(self.journal, flow.run_id).state, flow.state)

    def test_incomplete_full_inventory_observation_cannot_release_resources(self):
        flow, inputs, vessels, products, reagent = self.create()
        owners = copy.deepcopy(self.journal.owners())
        with self.assertRaises(ObservationError):
            flow.act('confirm_inventory', ACTOR, observations=self.observations(flow)[:-1])
        self.assertTrue(flow.state['recovery_required'])
        self.assertEqual(self.journal.owners(), owners)

    def test_claim_responsibility_is_separate_from_location_and_operator_custody_checks_actor(self):
        flow, inputs, vessels, products, reagent = self.create()
        for vessel in flow.state['inventory']['vessels'].values():
            self.assertEqual(vessel['responsibility']['actor_id'], ACTOR)
            self.assertEqual(vessel['location']['kind'], 'rack')
        held_vessel = flow.state['inventory']['materials'][reagent]['vessel_id']
        observations = self.observations(flow)
        for observation in observations:
            if observation['vessel_id'] == held_vessel:
                observation['location'] = {'kind': 'operator', 'actor_id': ACTOR}
        flow.act('confirm_inventory', ACTOR, observations=observations)
        held = flow.state['inventory']['vessels'][held_vessel]
        self.assertEqual(held['location'], {'kind': 'operator', 'actor_id': ACTOR})
        self.assertEqual(held['responsibility']['actor_id'], ACTOR)
        wrong = copy.deepcopy(observations)
        for observation in wrong:
            if observation['vessel_id'] == held_vessel:
                observation['location']['actor_id'] = 'SYN.ForeignOperator'
        with self.assertRaises(ObservationError):
            flow.act('confirm_inventory', ACTOR, observations=wrong)
        self.assertEqual(flow.state['inventory']['vessels'][held_vessel]['location'], held['location'])
        flow.act('reconcile', ACTOR, observations=observations, workspace_clear=False)
        two_held = copy.deepcopy(observations)
        next(item for item in two_held if item['vessel_id'] != held_vessel)['location'] = {
            'kind': 'operator', 'actor_id': ACTOR}
        with self.assertRaises(ObservationError):
            flow.act('confirm_inventory', ACTOR, observations=two_held)

    def test_only_empty_vessels_may_be_observed_discarded_and_products_remain_retained(self):
        flow, inputs, vessels, products, reagent = self.create()
        source = next(iter(products)); product, vessel = products[source]
        self.transform(flow, source, product, vessel)
        flow.act('set_disposition', ACTOR, material_id=product, disposition='retained', reason='Retain purified product')
        observations = self.observations(flow)
        empty = next(item for item in observations if item['vessel_id'] == 'SYN.ExtraTube.T1')
        self.assertEqual(empty['material_ids'], [])
        empty['location'] = {'kind': 'discarded'}
        flow.act('confirm_inventory', ACTOR, observations=observations)
        state = flow.state
        self.assertEqual(state['inventory']['vessels']['SYN.ExtraTube.T1']['location'], {'kind': 'discarded'})
        self.assertEqual(state['inventory']['materials'][product]['disposition'], 'retained')
        self.assertEqual(state['inventory']['materials'][product]['vessel_id'], vessel)
        revision = len(self.journal.history(flow.run_id))
        with self.assertRaises(TaskError):
            flow.act('begin_effect', ACTOR, intent_id='SYN.DiscardedTarget', kind='transformation',
                     inputs=[{'material_id': reagent, 'quantity': amount(5), 'consume_all': False}],
                     outputs=[{'material_id': 'SYN.DiscardedTarget.Product', 'kind': 'byproduct',
                               'vessel_id': 'SYN.ExtraTube.T1', 'role': 'invalid_discarded_target'}],
                     purpose='invalid_use_of_discarded_vessel')
        self.assertEqual(flow.state, state)
        self.assertEqual(len(self.journal.history(flow.run_id)), revision)
        self.assertNotIn('SYN.DiscardedTarget', flow.state['bookings'])
        self.assertNotIn('SYN.DiscardedTarget.Product', flow.state['inventory']['materials'])
        wrong = copy.deepcopy(observations)
        next(item for item in wrong if item['vessel_id'] == vessel)['location'] = {'kind': 'discarded'}
        with self.assertRaises(ObservationError):
            flow.act('confirm_inventory', ACTOR, observations=wrong)
        self.assertNotEqual(flow.state['inventory']['vessels'][vessel]['location'], {'kind': 'discarded'})
        self.assertEqual(flow.state['inventory']['materials'][product]['disposition'], 'retained')

    def test_legacy_journal_rows_remain_unchanged_and_readable(self):
        from nanodrop_manual import Workflow as NanoDrop
        legacy = NanoDrop.create(self.journal, run_id='SYN.Legacy.Before.Material')
        before = self.journal.connection.execute(
            'SELECT document,sha256 FROM events WHERE run_id=? ORDER BY sequence', (legacy.run_id,)).fetchall()
        legacy_state = legacy.state
        self.create()
        self.assertEqual(self.journal.connection.execute(
            'SELECT document,sha256 FROM events WHERE run_id=? ORDER BY sequence', (legacy.run_id,)).fetchall(), before)
        self.assertEqual(self.journal.state(legacy.run_id)[0], legacy_state)
        self.assertEqual(legacy.report()['format'], legacy.REPORT_FORMAT)

    def test_e1_compilers_remain_effect_free_after_material_lifecycle_extension(self):
        before = self.journal.connection.execute('SELECT count(*) FROM events').fetchone()[0]
        for compiler in [cutrun_preparation, extraction_preparation]:
            plan = compiler.compile_plan()
            self.assertFalse(plan['execution_ready'])
            self.assertTrue(all(value is False for value in plan['effects'].values()))
        self.assertEqual(self.journal.connection.execute('SELECT count(*) FROM events').fetchone()[0], before)


if __name__ == '__main__':
    unittest.main()
