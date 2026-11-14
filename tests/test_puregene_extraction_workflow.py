"""Puregene fraction retention and recovery on the shared extraction engine.

The database prefixes are independent synthetic test worlds, not stock transfer.
"""
import copy
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dneasy_extraction_workflow import DNeasyWorkflow
from extraction_workflow import ExtractionWorkflow
from manual_tasks import Journal, TaskError
from manual_workflow import ObservationError
import material_ledger as ledger
from puregene_extraction_sources import load
from puregene_extraction_workflow import PuregeneWorkflow

ACTOR = 'SYN.Puregene.Unit.Operator'
RUN = 'SYN.PUREGENE.Unit'
REASON = 'Explicit synthetic Puregene unit-test observation; no biochemical or hardware execution.'


def phase_observations(step):
    value = {name: True for name in step['required_checks']}; parameters = step['parameters']
    if 'duration_s' in parameters: value['duration_s'] = parameters['duration_s']
    if 'temperature_min_deg_c' in parameters:
        value['temperature_deg_c'] = (parameters['temperature_min_deg_c'] + parameters['temperature_max_deg_c']) / 2
    if 'rcf_min_x_g' in parameters: value['rcf_x_g'] = parameters['rcf_min_x_g']
    if 'inversion_count' in parameters: value['inversion_count'] = parameters['inversion_count']
    return value


def actual_inputs(flow, intent):
    state = flow.state; result = []
    for item in state['bookings'][intent]['request']['inputs']:
        quantity = copy.deepcopy(item['quantity'])
        if item['consume_all']:
            balance = ledger.remaining(state, item['material_id'], exclude_intent=intent)
            quantity = {'value': balance['value'], 'unit': balance['unit']}
        result.append({'material_id': item['material_id'], 'quantity': quantity})
    return result


def perform(flow, phase_id, *, confirm=True):
    step = next(value for value in flow.state['definition']['execution']['steps'] if value['id'] == phase_id)
    sample_id = next(iter(flow.state['definition']['execution']['samples']))
    intent = 'Unit.Phase.' + phase_id
    flow.act('begin_phase', ACTOR, sample_id=sample_id, phase_id=phase_id, intent_id=intent)
    if step['parameters'].get('duration_s'):
        flow.act('advance_time', ACTOR, seconds=step['parameters']['duration_s'])
    receipt = {'intent_id': intent, 'actual_inputs': actual_inputs(flow, intent) if intent in flow.state['bookings'] else [],
        'actual_outputs': copy.deepcopy(step['fixture_actual_outputs']),
        'observations': phase_observations(step), 'reason': REASON}
    if confirm: flow.act('confirm_phase', ACTOR, **receipt)
    return receipt


def advance(flow, stop_before=None):
    while flow.state['process']['cursor'] < len(flow.state['definition']['execution']['steps']):
        step = flow.state['definition']['execution']['steps'][flow.state['process']['cursor']]
        if step['id'] == stop_before: return
        perform(flow, step['id'])


def ancestors(state, material_id):
    result = set(); pending = [material_id]
    while pending:
        current = pending.pop()
        for parent in state['inventory']['materials'][current]['parents']:
            if parent not in result: result.add(parent); pending.append(parent)
    return result


class PuregeneWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'exports').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='puregene-unit-prefix-', dir=ROOT / 'exports')
        cls.addClassCleanup(cls.temp.cleanup); cls.folder = Path(cls.temp.name)
        cls.prefix = cls.folder / 'protein-separated.sqlite3'
        with Journal(cls.prefix) as journal:
            flow = PuregeneWorkflow.create(journal, run_id=RUN)
            flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
            flow.act('workspace_clear', ACTOR, confirmed=True); flow.act('claim', ACTOR)
            advance(flow, 'prepare_isopropanol_receiver'); flow.close()
        cls.dry = cls.folder / 'before-drying.sqlite3'; shutil.copyfile(cls.prefix, cls.dry)
        with Journal(cls.dry) as journal:
            flow = PuregeneWorkflow.open(journal, RUN)
            flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
            advance(flow, 'air_dry_pellet'); flow.close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.folder)
        self.addCleanup(self.temp.cleanup); self.directory = Path(self.temp.name)

    def open(self, mode='protein'):
        path = self.directory / (mode + '.sqlite3')
        if mode != 'fresh': shutil.copyfile(self.prefix if mode == 'protein' else self.dry, path)
        journal = Journal(path); self.addCleanup(journal.close)
        if mode == 'fresh':
            flow = PuregeneWorkflow.create(journal, run_id=RUN)
            flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
            flow.act('workspace_clear', ACTOR, confirmed=True); flow.act('claim', ACTOR)
        else:
            flow = PuregeneWorkflow.open(journal, RUN)
            flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
        self.addCleanup(flow.close)
        return flow

    def cancel(self, flow):
        flow.act('cancel', ACTOR, reason=REASON)
        for identity, material in flow.state['inventory']['materials'].items():
            if material['disposition'] in {'consumed', 'discarded'}: continue
            disposition = ('quarantined' if material['disposition'] == 'quarantined' else
                           'retained' if material['kind'] in {'reagent', 'sample', 'product'} else 'discarded')
            flow.act('set_disposition', ACTOR, material_id=identity, disposition=disposition, reason=REASON)
        flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
        flow.act('finish_cancel', ACTOR, workspace_clear=True)

    def test_both_chemistries_share_engine_and_reject_each_others_state(self):
        flow = self.open('fresh')
        self.assertIs(PuregeneWorkflow._confirm, DNeasyWorkflow._confirm)
        self.assertIs(PuregeneWorkflow._begin_tapestation, DNeasyWorkflow._begin_tapestation)
        self.assertTrue(issubclass(PuregeneWorkflow, ExtractionWorkflow))
        with self.assertRaises(TaskError): DNeasyWorkflow(flow.journal, RUN, flow.session)
        with self.assertRaises(TaskError): ExtractionWorkflow(flow.journal, RUN, flow.session)
        self.assertNotIn('samples', flow.state); self.assertNotIn('derived_vessels', flow.state)

    def test_protein_pellet_and_supernatant_coexist_as_one_material_until_transfer(self):
        flow = self.open(); state = flow.state
        sample_id, binding = next(iter(state['definition']['execution']['samples'].items()))
        vessel = binding['input_vessel_id']
        occupants = [value for value in state['inventory']['materials'].values() if value['vessel_id'] == vessel]
        self.assertEqual(len(occupants), 1)
        self.assertEqual(occupants[0]['id'], sample_id + '.protein_composite')
        self.assertNotIn(sample_id + '.protein_pellet', state['inventory']['materials'])
        retained = state['process']['retention'][sample_id]
        self.assertTrue(retained['confirmed']); self.assertEqual(retained['planned']['pellet'], 'protein')
        self.assertEqual(retained['planned']['retained'], 'supernatant')
        self.assertFalse(any('quantity' in key for key in retained['planned']))

    def test_aspiration_creates_real_tip_transfer_and_leaves_protein_pellet_without_ipa_ancestry(self):
        flow = self.open(); perform(flow, 'prepare_isopropanol_receiver'); perform(flow, 'aspirate_dna_supernatant')
        state = flow.state; sample_id, binding = next(iter(state['definition']['execution']['samples'].items()))
        pellet = state['inventory']['materials'][sample_id + '.protein_pellet']
        supernatant = state['inventory']['materials'][sample_id + '.dna_supernatant']
        self.assertEqual(pellet['vessel_id'], binding['input_vessel_id'])
        self.assertEqual(supernatant['vessel_id'], binding['fraction_vessels']['transfer_tip'])
        self.assertNotIn(binding['reagent_bindings']['Isopropanol'], ancestors(state, pellet['id']))
        perform(flow, 'dispense_into_isopropanol'); state = flow.state
        composite = sample_id + '.dna_ipa_composite'
        self.assertIn(binding['reagent_bindings']['Isopropanol'], ancestors(state, composite))
        self.assertNotIn(binding['reagent_bindings']['Isopropanol'], ancestors(state, pellet['id']))

    def test_tip_and_dispense_intent_survive_restart_without_automatic_effect(self):
        flow = self.open(); perform(flow, 'prepare_isopropanol_receiver'); perform(flow, 'aspirate_dna_supernatant')
        receipt = perform(flow, 'dispense_into_isopropanol', confirm=False)
        before = flow.state; flow.close()
        reopened = PuregeneWorkflow.open(flow.journal, RUN, resume=True); self.addCleanup(reopened.close)
        self.assertEqual(reopened.state['bookings'], before['bookings'])
        sample_id, binding = next(iter(before['definition']['execution']['samples'].items()))
        self.assertEqual(reopened.state['inventory']['materials'][sample_id + '.dna_supernatant']['vessel_id'],
                         binding['fraction_vessels']['transfer_tip'])
        self.assertIn('vessel:' + binding['fraction_vessels']['transfer_tip'], reopened.state['resources'])
        with self.assertRaises(TaskError): reopened.act('confirm_phase', ACTOR, **receipt)
        reopened.act('resolve_effect', ACTOR, outcome='performed', **receipt)
        self.assertIsNotNone(reopened.state['recovery_required'])
        reopened.act('reconcile', ACTOR, observations=reopened.inventory_observations(), workspace_clear=True)
        self.assertEqual(reopened.state['inventory']['materials'][sample_id + '.dna_supernatant']['disposition'], 'consumed')

    def test_dna_pellet_survives_liquid_removals_and_drying_without_zero_volume_conversion(self):
        flow = self.open('dry'); state = flow.state
        sample_id, binding = next(iter(state['definition']['execution']['samples'].items()))
        pellet = state['inventory']['materials'][sample_id + '.washed_dna_pellet']
        self.assertEqual(pellet['vessel_id'], binding['fraction_vessels']['precipitation'])
        self.assertEqual(pellet['initial_quantity'], {'value': None, 'unit': 'ng'})
        before_bookings = copy.deepcopy(state['bookings'])
        perform(flow, 'air_dry_pellet'); after = flow.state
        self.assertEqual(after['bookings'], before_bookings)
        self.assertEqual(after['inventory']['materials'][pellet['id']]['initial_quantity'], {'value': None, 'unit': 'ng'})
        self.assertEqual(after['inventory']['materials'][pellet['id']]['vessel_id'], binding['fraction_vessels']['precipitation'])

    def test_zero_observed_pellet_amount_is_booked_but_blocks_nominal_progress(self):
        flow = self.open(); advance(flow, 'remove_isopropanol_supernatant')
        receipt = perform(flow, 'remove_isopropanol_supernatant', confirm=False)
        receipt['actual_outputs'][0]['quantity']['value'] = 0
        flow.act('confirm_phase', ACTOR, **receipt)
        self.assertTrue(flow.state['process']['deviations'])
        with self.assertRaises(TaskError): perform(flow, 'add_ethanol_wash')
        self.assertFalse(flow.report()['passed'])

    def test_zero_observed_supernatant_transfer_is_booked_but_not_nominal_retention(self):
        flow = self.open(); perform(flow, 'prepare_isopropanol_receiver')
        receipt = perform(flow, 'aspirate_dna_supernatant', confirm=False)
        sample_id = next(iter(flow.state['definition']['execution']['samples']))
        material_id = sample_id + '.dna_supernatant'
        for output in receipt['actual_outputs']:
            if output['material_id'] == material_id: output['quantity']['value'] = 0
        flow.act('confirm_phase', ACTOR, **receipt)
        self.assertEqual(flow.state['bookings'][receipt['intent_id']]['outcome'], 'performed')
        self.assertEqual(ledger.remaining(flow.state, material_id)['value'], 0)
        self.assertTrue(flow.state['process']['deviations'])
        self.assertFalse(flow.state['process']['retention'][sample_id]['confirmed'])
        with self.assertRaises(TaskError): perform(flow, 'dispense_into_isopropanol')
        self.assertFalse(flow.report()['passed'])

    def test_zero_prefilled_isopropanol_receiver_is_not_nominal_preparation(self):
        flow = self.open(); receipt = perform(flow, 'prepare_isopropanol_receiver', confirm=False)
        receipt['actual_outputs'][0]['quantity']['value'] = 0
        flow.act('confirm_phase', ACTOR, **receipt)
        self.assertEqual(flow.state['bookings'][receipt['intent_id']]['outcome'], 'performed')
        self.assertEqual(ledger.remaining(flow.state, receipt['actual_outputs'][0]['material_id'])['value'], 0)
        self.assertTrue(flow.state['process']['deviations'])
        with self.assertRaises(TaskError): perform(flow, 'aspirate_dna_supernatant')
        self.assertFalse(flow.report()['passed'])

    def test_abnormal_overdry_preserves_false_checks_and_allows_truthful_abort(self):
        flow = self.open('dry'); receipt = perform(flow, 'air_dry_pellet', confirm=False)
        receipt['observations']['pellet_not_overdried_confirmed'] = False
        receipt['observations']['dna_pellet_retained_confirmed'] = False
        with self.assertRaises(ObservationError): flow.act('confirm_phase', ACTOR, **receipt)
        flow.act('resolve_effect', ACTOR, outcome='performed_abnormal', **receipt)
        state = flow.state; sample_id = next(iter(state['definition']['execution']['samples']))
        operation = state['process']['operations'][receipt['intent_id']]
        self.assertEqual(operation['state'], 'performed')
        self.assertFalse(operation['confirmation']['observations']['dna_pellet_retained_confirmed'])
        self.assertFalse(state['process']['retention'][sample_id]['confirmed'])
        self.assertEqual(state['inventory']['materials'][sample_id + '.washed_dna_pellet']['disposition'], 'quarantined')
        flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
        with self.assertRaises(TaskError): perform(flow, 'add_hydration_solution')
        self.cancel(flow)
        self.assertEqual(flow.state['status'], 'cancelled'); self.assertFalse(flow.report()['passed'])

    def test_excess_rcf_is_not_hidden_by_minimum_only_check(self):
        flow = self.open('fresh'); advance(flow, 'spin_protein_precipitate')
        receipt = perform(flow, 'spin_protein_precipitate', confirm=False)
        receipt['observations']['rcf_x_g'] = 17000
        with self.assertRaises(ObservationError): flow.act('confirm_phase', ACTOR, **receipt)
        flow.act('resolve_effect', ACTOR, outcome='performed_abnormal', **receipt)
        self.assertEqual(flow.state['process']['operations'][receipt['intent_id']]['confirmation']['observations']['rcf_x_g'], 17000)
        self.assertTrue(flow.state['process']['deviations'])
        self.cancel(flow)
        self.assertEqual(flow.state['resources'], [])

    def test_abnormal_mixing_after_dispense_quarantines_live_dna_composite(self):
        flow = self.open(); advance(flow, 'mix_dna_precipitation')
        receipt = perform(flow, 'mix_dna_precipitation', confirm=False)
        receipt['observations']['inversion_count'] = 49
        with self.assertRaises(ObservationError): flow.act('confirm_phase', ACTOR, **receipt)
        flow.act('resolve_effect', ACTOR, outcome='performed_abnormal', **receipt)
        state = flow.state; sample_id = next(iter(state['definition']['execution']['samples']))
        material_id = sample_id + '.dna_ipa_composite'
        self.assertEqual(state['inventory']['materials'][material_id]['disposition'], 'quarantined')
        self.assertFalse(state['process']['retention'][sample_id]['confirmed'])
        self.assertEqual(state['process']['retention'][sample_id]['planned']['material_id'], material_id)
        self.cancel(flow)
        self.assertFalse(flow.report()['passed']); self.assertEqual(flow.state['resources'], [])

    def test_abnormal_resolution_rejects_malformed_and_nonfinite_observations(self):
        flow = self.open('dry'); receipt = perform(flow, 'air_dry_pellet', confirm=False)
        flow.act('mark_effect_unknown', ACTOR, intent_id=receipt['intent_id'], reason=REASON)
        before = flow.journal.history(RUN)
        for mutation in [lambda row: row.update(extra=True), lambda row: row.update(duration_s=math.nan),
                         lambda row: row.update(duration_s=-1),
                         lambda row: row.update(dna_pellet_retained_confirmed='false')]:
            bad = copy.deepcopy(receipt); mutation(bad['observations'])
            with self.assertRaises(TaskError): flow.act('resolve_effect', ACTOR, outcome='performed_abnormal', **bad)
            self.assertEqual(flow.journal.history(RUN), before)

    def test_logical_elapsed_over_maximum_cannot_be_hidden_by_short_reported_duration(self):
        operation = {'started_at_s': 0, 'request': {'parameters': {'duration_s': 300, 'duration_max_s': 600},
                     'required_checks': ['pellet_retained']}}
        state = {'logical_time_s': 601}
        with self.assertRaises(ObservationError):
            ExtractionWorkflow._phase_observations(state, operation, {'pellet_retained': True, 'duration_s': 300})
        deviations = ExtractionWorkflow._phase_observations(state, operation,
            {'pellet_retained': False, 'duration_s': 300}, abnormal=True)
        self.assertTrue(deviations)

    def test_inversion_count_requires_exact_integer_and_source_bound_value(self):
        operation = {'started_at_s': 0, 'request': {'parameters': {'inversion_count': 50}, 'required_checks': []}}
        state = {'logical_time_s': 0}
        for value in [49, 51]:
            with self.assertRaises(ObservationError):
                ExtractionWorkflow._phase_observations(state, operation, {'inversion_count': value})
        for value in [True, 50.5, math.inf]:
            with self.assertRaises(TaskError):
                ExtractionWorkflow._phase_observations(state, operation, {'inversion_count': value}, abnormal=True)
        self.assertEqual(ExtractionWorkflow._phase_observations(state, operation, {'inversion_count': 50}), [])

    def test_overnight_duration_is_an_explicit_fixture_setting_and_limits_remain_open(self):
        flow = self.open('dry'); advance(flow, 'overnight_hydration')
        step = next(value for value in flow.state['definition']['execution']['steps'] if value['id'] == 'overnight_hydration')
        self.assertEqual(step['parameters']['duration_s'], 43200)
        self.assertIn('synthetic_fixture', step['parameter_scopes']['duration_s'])
        report = flow.report()
        self.assertFalse(report['passed']); self.assertFalse(report['biochemical_protocol_executed'])
        self.assertTrue(any('Overnight' in value for value in report['limitations']))
        self.assertFalse(any('single elution' in value.lower() for value in report['limitations']))


if __name__ == '__main__':
    unittest.main()
