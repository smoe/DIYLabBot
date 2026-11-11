"""Existing device operations consume one DNA root inventory across attempts."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from manual_tasks import TaskError, digest
from manual_workflow import ObservationError
from nanodrop_manual import load_profile as load_nanodrop
from qubit_manual import load_profile as load_qubit, next_preparation, calibration_binding
from dna_quantification_ledger import reserve_withdrawal, confirm_withdrawal, remaining
from dna_quantification_stages import make_context, build_adapter

ACTOR = 'SYN.DNA.Operator'
SAMPLE = 'DNA01'


class DeviceContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.devices = {'nanodrop': load_nanodrop(), 'qubit': load_qubit()}
        cls.devices['qubit']['profile']['parameters'].update(
            sample_volume_ul=2, standard_volume_ul=10, assay_total_volume_ul=200,
            incubation_min_s=120, incubation_max_s=None, calibration_validity_s=1000,
            task_deadline_s=10000)

    def setUp(self):
        def vessel(identity, kind, slot, rack, amount, sample=SAMPLE):
            home = {'kind': 'rack', 'rack_id': rack, 'place_id': 'Slot%02d' % slot}
            return {'id': identity, 'kind': kind,
                    'origin': 'original' if kind == 'original' else 'derived',
                    'sample_id': sample, 'home': home, 'location': copy.deepcopy(home),
                    'initial_volume_ul': amount, 'content_revision': 0,
                    'volume_uncertain': False, 'mass_confirmation_valid': False,
                    'return_confirmation': {'actor_id': ACTOR, 'evidence': 'synthetic_input'}}

        self.root = {'run_id': 'SYN.DNA.CONTEXT', 'logical_time_s': 0.,
            'definition': {'devices': copy.deepcopy(self.devices)},
            'contexts': {}, 'bookings': {}, 'resources': [
                'rack:SYN.Input', 'rack:SYN.Dilutions', 'vessel:Original',
                'vessel:Dilution', 'workspace:SYN.Bench',
                'instrument:SYN.NanoDrop01', 'instrument:SYN.Qubit401'],
            'inventory': {'vessels': {
                'Original': vessel('Original', 'original', 1, 'SYN.Input', 40),
                'Dilution': vessel('Dilution', 'dilution', 2, 'SYN.Dilutions', 20),
                'OtherDilution': vessel('OtherDilution', 'dilution', 3, 'SYN.Dilutions', 25)}}}
        self.artifacts = {}
        self.flow = SimpleNamespace(journal=SimpleNamespace(artifact=self.artifacts.__getitem__))

    def adapter(self, device='nanodrop', attempt='SYN.DNA.CONTEXT.DNA01.A01', source='Dilution'):
        context = make_context(self.root, device, attempt, SAMPLE, source)
        return build_adapter(self.flow, self.root, context['id'])

    @staticmethod
    def claim(adapter):
        adapter._workspace_clear(adapter.state, ACTOR, confirmed=True)
        adapter._claim(adapter.state, ACTOR)

    @staticmethod
    def take(adapter):
        sample = adapter.state['samples'][SAMPLE]
        adapter._take(adapter.state, ACTOR, sample_id=SAMPLE, observed_sample_id=SAMPLE,
                      rack_id=sample['location']['rack_id'], place_id=sample['original_place_id'])

    def reserve(self, adapter):
        pending = adapter._pending(adapter.state)
        return reserve_withdrawal(self.root, intent_id=pending['intent_id'],
            source_vessel_id=adapter.context['source_vessel_id'],
            planned_volume_ul=adapter.state['definition']['profile']['parameters']['sample_volume_ul'],
            stage_id=adapter.context['id'], attempt_id=adapter.context['attempt_id'],
            target={'kind': 'assay_or_discard'}, actor_id=ACTOR)

    def begin_nanodrop(self, adapter):
        self.claim(adapter)
        adapter._blank(adapter.state, ACTOR, reference_id='SYN.Blank', cleaned=True)
        self.take(adapter)
        adapter._begin_measurement(adapter.state, ACTOR, sample_id=SAMPLE,
            measurement_id=adapter.state['planned_measurements'][SAMPLE])
        self.reserve(adapter)

    def prepare_standard(self, adapter):
        identity = next_preparation(adapter.state)
        target = adapter.state['definition']['protocol']['assay']['standards'][0]['id']
        holder = adapter.holder_places()[0]
        adapter._begin_preparation(adapter.state, ACTOR, kind='standard', target_id=target,
            vessel_id=identity + '.Tube', observed_vessel_id=identity + '.Tube',
            empty_tube_confirmed=True, **holder)
        pending = copy.deepcopy(adapter._pending(adapter.state))
        adapter._confirm_preparation(adapter.state, ACTOR, intent_id=pending['intent_id'],
            observed_vessel_id=pending['vessel_id'], volume_ul=10,
            assay_total_volume_ul=200, mixed=True)
        return identity

    def calibrate(self, adapter):
        standards = adapter.state['definition']['protocol']['assay']['standards']
        measurements = {}
        for index, target in enumerate(standards):
            identity = next_preparation(adapter.state)
            adapter._begin_preparation(adapter.state, ACTOR, kind='standard', target_id=target['id'],
                vessel_id=identity + '.Tube', observed_vessel_id=identity + '.Tube',
                empty_tube_confirmed=True, **adapter.holder_places()[index])
            pending = copy.deepcopy(adapter._pending(adapter.state))
            adapter._confirm_preparation(adapter.state, ACTOR, intent_id=pending['intent_id'],
                observed_vessel_id=pending['vessel_id'], volume_ul=10,
                assay_total_volume_ul=200, mixed=True)
            adapter._advance_time(adapter.state, ACTOR, seconds=120)
            preparation = adapter.state['preparations'][identity]
            adapter._begin_measurement(adapter.state, ACTOR, preparation_id=identity,
                measurement_id=preparation['measurement_id'], observed_vessel_id=pending['vessel_id'])
            measurement_intent = adapter._pending(adapter.state)['intent_id']
            adapter._confirm_measurement(adapter.state, ACTOR, intent_id=measurement_intent,
                observed_vessel_id=pending['vessel_id'], returned_to_holder=True)
            measurements[target['id']] = preparation['measurement_id']
        adapter._approve_calibration(adapter.state, ACTOR, binding=calibration_binding(adapter.state),
            standard_measurements=measurements, confirmed=True, reason='Synthetic calibration approval')

    def test_prediluted_input_is_same_canonical_vessel_and_never_a_new_volume_credit(self):
        adapter = self.adapter()
        state = adapter.state
        self.assertEqual(state['definition']['profile']['rack']['id'], 'SYN.Dilutions')
        self.assertEqual(state['definition']['profile']['samples'], [
            {'id': SAMPLE, 'vessel_id': 'Dilution', 'rack_slot': 2, 'initial_volume_ul': None}])
        self.assertEqual(state['samples'][SAMPLE]['remaining_volume_ul'], 20)
        for field in ['initial_volume_ul', 'remaining_volume_ul', 'vessel_id', 'original_place_id']:
            with self.subTest(field=field):
                with self.assertRaises(TaskError): state['samples'][SAMPLE][field] = 1000
        reserve_withdrawal(self.root, intent_id='external-before-context', source_vessel_id='Dilution',
            planned_volume_ul=2, stage_id='other-context', attempt_id='earlier',
            target={'kind': 'discard'}, actor_id=ACTOR)
        self.assertIsNone(state['samples'][SAMPLE]['remaining_volume_ul'])
        confirm_withdrawal(self.root, 'external-before-context', 2)
        self.assertEqual(state['samples'][SAMPLE]['remaining_volume_ul'], 18)
        self.assertEqual(remaining(self.root, 'Original'), 40)
        self.assertNotIn('samples', adapter.context['local'])
        self.assertNotIn('derived_vessels', adapter.context['local'])
        json.dumps(self.root, allow_nan=False)

    def test_nanodrop_consumes_dilution_once_and_returns_it_to_its_own_rack(self):
        adapter = self.adapter()
        self.begin_nanodrop(adapter)
        pending = copy.deepcopy(adapter._pending(adapter.state))
        self.assertIsNone(remaining(self.root, 'Dilution'))
        adapter._confirm_measurement(adapter.state, ACTOR, intent_id=pending['intent_id'],
            observed_sample_id=SAMPLE, volume_ul=1.5, cleaned=True)
        self.assertEqual(remaining(self.root, 'Dilution'), 18.5)
        self.assertEqual(remaining(self.root, 'Original'), 40)
        self.assertEqual(self.root['inventory']['vessels']['Dilution']['content_revision'], 1)
        with self.assertRaises(TaskError):
            adapter._confirm_measurement(adapter.state, ACTOR, intent_id=pending['intent_id'],
                observed_sample_id=SAMPLE, volume_ul=1.5, cleaned=True)
        with self.assertRaises(ObservationError):
            adapter._place(adapter.state, ACTOR, sample_id=SAMPLE, observed_sample_id=SAMPLE,
                           rack_id='SYN.Input', place_id='Slot01')
        adapter._place(adapter.state, ACTOR, sample_id=SAMPLE, observed_sample_id=SAMPLE,
                       rack_id='SYN.Dilutions', place_id='Slot02')
        self.assertEqual(self.root['inventory']['vessels']['Dilution']['location'],
                         self.root['inventory']['vessels']['Dilution']['home'])

    def test_device_release_retains_root_reservations_and_preserves_raw_import(self):
        adapter = self.adapter()
        self.begin_nanodrop(adapter)
        pending = adapter._pending(adapter.state)
        adapter._confirm_measurement(adapter.state, ACTOR, intent_id=pending['intent_id'],
                                     observed_sample_id=SAMPLE, volume_ul=1.5, cleaned=True)
        adapter._place(adapter.state, ACTOR, sample_id=SAMPLE, observed_sample_id=SAMPLE,
                       rack_id='SYN.Dilutions', place_id='Slot02')
        measurement = adapter.state['planned_measurements'][SAMPLE]
        content = ('Sample Name,ng/uL,Factor\n' + measurement + ',25,50\n').encode()
        self.artifacts[digest(content)] = content
        adapter._import_results(adapter.state, content, 'synthetic.csv')
        adapter._review_results(adapter.state, ACTOR, decision='accepted', reason='Synthetic review')
        resources = self.root['resources'][:]
        adapter._release(adapter.state, ACTOR, workspace_clear=True)
        self.assertEqual(adapter.state['status'], 'completed')
        self.assertEqual(self.root['resources'], resources)
        self.assertEqual(self.artifacts[digest(content)], content)
        self.assertEqual(adapter.state['results'][measurement]['raw_cells']['Factor'], '50')

    def test_new_contexts_have_new_ids_and_cannot_start_from_an_uncertain_source(self):
        first = self.adapter()
        with self.assertRaises(TaskError):
            make_context(self.root, 'nanodrop', first.context['attempt_id'], SAMPLE, 'Dilution')
        second = self.adapter(attempt='SYN.DNA.CONTEXT.DNA01.A02')
        self.assertNotEqual(first.state['planned_measurements'], second.state['planned_measurements'])
        self.root['inventory']['vessels']['Dilution']['volume_uncertain'] = True
        with self.assertRaises(TaskError):
            self.adapter(attempt='SYN.DNA.CONTEXT.DNA01.A03')

    def test_qubit_preparation_debits_selected_dilution_only_and_measurement_is_not_a_debit(self):
        adapter = self.adapter(device='qubit')
        self.claim(adapter);self.calibrate(adapter);self.take(adapter)
        identity = next_preparation(adapter.state)
        adapter._begin_preparation(adapter.state, ACTOR, kind='sample', target_id=SAMPLE,
            vessel_id=identity + '.Tube', observed_vessel_id=identity + '.Tube',
            empty_tube_confirmed=True, **adapter.holder_places()[2])
        self.reserve(adapter)
        pending = copy.deepcopy(adapter._pending(adapter.state))
        adapter._confirm_preparation(adapter.state, ACTOR, intent_id=pending['intent_id'],
            observed_vessel_id=pending['vessel_id'], observed_sample_id=SAMPLE,
            volume_ul=2, assay_total_volume_ul=200, mixed=True)
        self.assertEqual(remaining(self.root, 'Original'), 40)
        self.assertEqual(remaining(self.root, 'Dilution'), 18)
        self.assertEqual(adapter.state['transfers'][identity + '.Transfer']['source']['vessel_id'], 'Dilution')
        self.assertNotIn('OtherDilution', adapter.state['derived_vessels'])
        self.assertNotIn('Dilution', adapter.state['derived_vessels'])
        self.assertEqual(set(adapter.state['derived_vessels']),
                         {p['vessel_id'] for p in adapter.state['preparations'].values()})
        adapter._place(adapter.state, ACTOR, sample_id=SAMPLE, observed_sample_id=SAMPLE,
                       rack_id='SYN.Dilutions', place_id='Slot02')
        adapter._advance_time(adapter.state, ACTOR, seconds=120)
        preparation = adapter.state['preparations'][identity]
        adapter._begin_measurement(adapter.state, ACTOR, preparation_id=identity,
            measurement_id=preparation['measurement_id'], observed_vessel_id=pending['vessel_id'],
            calibration_id=adapter.state['calibration']['id'])
        measurement_intent = adapter._pending(adapter.state)['intent_id']
        adapter._confirm_measurement(adapter.state, ACTOR, intent_id=measurement_intent,
            observed_vessel_id=pending['vessel_id'], returned_to_holder=True)
        self.assertEqual(remaining(self.root, 'Dilution'), 18)
        self.assertEqual(len(self.root['bookings']), 1)
        # Disposal of an identified assay tube does not consume its DNA source again.
        adapter._dispose_vessel(adapter.state, ACTOR, vessel_id=pending['vessel_id'],
            observed_vessel_id=pending['vessel_id'], reason='Synthetic disposal')
        self.assertEqual(remaining(self.root, 'Dilution'), 18)

    def test_confirmation_rejects_foreign_context_booking_without_debit(self):
        adapter = self.adapter()
        self.begin_nanodrop(adapter)
        pending = adapter._pending(adapter.state)
        self.root['bookings'][pending['intent_id']]['stage_id'] = 'another-context'
        with self.assertRaisesRegex(TaskError, 'matching context withdrawal'):
            adapter._confirm_measurement(adapter.state, ACTOR, intent_id=pending['intent_id'],
                observed_sample_id=SAMPLE, volume_ul=1.5, cleaned=True)
        self.assertEqual(self.root['bookings'][pending['intent_id']]['outcome'], 'intent')
        self.assertIsNone(self.root['bookings'][pending['intent_id']]['actual_volume_ul'])
        self.assertEqual(self.root['inventory']['vessels']['Dilution']['content_revision'], 0)
        self.assertEqual(remaining(self.root, 'Original'), 40)

    def test_qubit_standards_never_book_dna_and_chamber_is_not_a_holder(self):
        adapter = self.adapter(device='qubit')
        self.claim(adapter)
        identity = next_preparation(adapter.state)
        standard = adapter.state['definition']['protocol']['assay']['standards'][0]['id']
        with self.assertRaisesRegex(TaskError, 'chamber is not storage'):
            adapter._begin_preparation(adapter.state, ACTOR, kind='standard', target_id=standard,
                vessel_id=identity + '.Tube', observed_vessel_id=identity + '.Tube',
                holder_id='SYN.Qubit401', place_id='Chamber', empty_tube_confirmed=True)
        self.assertEqual(adapter.context['derived_vessel_ids'], [])
        self.prepare_standard(adapter)
        self.assertEqual(self.root['bookings'], {})
        self.assertEqual(remaining(self.root, 'Original'), 40)
        self.assertEqual(remaining(self.root, 'Dilution'), 20)

    def test_qubit_measurement_requires_return_to_exact_recorded_holder(self):
        adapter = self.adapter(device='qubit')
        self.claim(adapter)
        identity = self.prepare_standard(adapter)
        adapter._advance_time(adapter.state, ACTOR, seconds=120)
        preparation = adapter.state['preparations'][identity]
        vessel_id = preparation['vessel_id']
        vessel = adapter.state['derived_vessels'][vessel_id]
        original = copy.deepcopy(vessel['location'])
        vessel['location'] = {'kind': 'logical', 'holder_id': 'SYN.Qubit401', 'place_id': 'Chamber'}
        with self.assertRaises(TaskError):
            adapter._begin_measurement(adapter.state, ACTOR, preparation_id=identity,
                measurement_id=preparation['measurement_id'], observed_vessel_id=vessel_id)
        vessel['location'] = original
        adapter._begin_measurement(adapter.state, ACTOR, preparation_id=identity,
            measurement_id=preparation['measurement_id'], observed_vessel_id=vessel_id)
        pending = copy.deepcopy(adapter._pending(adapter.state))
        vessel['location'] = {'kind': 'logical', **adapter.holder_places()[1]}
        with self.assertRaises(ObservationError):
            adapter._confirm_measurement(adapter.state, ACTOR, intent_id=pending['intent_id'],
                observed_vessel_id=vessel_id, returned_to_holder=True)
        vessel['location'] = original
        adapter._confirm_measurement(adapter.state, ACTOR, intent_id=pending['intent_id'],
            observed_vessel_id=vessel_id, returned_to_holder=True)
        self.assertTrue(adapter.state['measurements'][preparation['measurement_id']]['valid'])
        self.assertEqual(self.root['bookings'], {})

    def test_derived_vessel_history_cannot_be_reused_from_another_context(self):
        first = self.adapter(device='qubit')
        self.claim(first)
        identity = self.prepare_standard(first)
        old_vessel = first.state['preparations'][identity]['vessel_id']
        second = self.adapter(device='qubit', attempt='SYN.DNA.CONTEXT.DNA01.A02')
        self.assertEqual(list(second.state['derived_vessels']), [])
        with self.assertRaises(TaskError):
            second.state['derived_vessels'][old_vessel] = copy.deepcopy(
                first.state['derived_vessels'][old_vessel])
        self.assertEqual(list(second.state['derived_vessels']), [])

    def test_clock_and_deadline_remain_root_and_context_projections(self):
        adapter = self.adapter(device='qubit')
        self.claim(adapter)
        deadline = adapter.state['deadline_s']
        adapter._advance_time(adapter.state, ACTOR, seconds=120)
        self.assertEqual(self.root['logical_time_s'], 120)
        self.assertNotIn('logical_time_s', adapter.context['local'])
        self.assertEqual(adapter.state['deadline_s'], deadline)
        adapter._advance_time(adapter.state, ACTOR, seconds=deadline)
        self.assertEqual(adapter.state['recovery_required'], 'deadline_exceeded')
        self.assertFalse(adapter.state['workspace_clear'])
        self.assertEqual(adapter.state['deadline_s'], deadline)


if __name__ == '__main__':
    unittest.main()
