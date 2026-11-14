"""Synthetic DNeasy phases, true material effects, recovery and TapeStation QC.

Copied prefixes are independent test worlds, never supported stock handoff.
"""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dneasy_extraction_sources import SOURCE, load
from dneasy_extraction_workflow import DNeasyWorkflow
from manual_tasks import Journal, TaskError, digest
from manual_workflow import ObservationError
from material_workflow import MaterialWorkflow
import material_ledger as ledger
from tapestation_results import synthetic_report

ACTOR = 'SYN.DNeasy.Unit.Operator'
RUN = 'SYN.DNEASY.Unit'
REASON = 'Explicit synthetic unit-test observation; no biochemical or hardware effect.'


def actual_inputs(flow, intent):
    state = flow.state
    result = []
    for item in state['bookings'][intent]['request']['inputs']:
        quantity = copy.deepcopy(item['quantity'])
        if item['consume_all']:
            balance = ledger.remaining(state, item['material_id'], exclude_intent=intent)
            quantity = {'value': balance['value'], 'unit': balance['unit']}
        result.append({'material_id': item['material_id'], 'quantity': quantity})
    return result


def observations(step):
    result = {key: True for key in step['required_checks']}
    params = step['parameters']
    if 'duration_s' in params: result['duration_s'] = params['duration_s']
    if 'temperature_min_deg_c' in params:
        result['temperature_deg_c'] = (params['temperature_min_deg_c'] + params['temperature_max_deg_c']) / 2
    if 'rcf_min_x_g' in params: result['rcf_x_g'] = params['rcf_min_x_g']
    return result


def phase(flow, step, *, confirm=True, intent=None):
    intent = intent or 'Unit.Phase.' + step['id']
    flow.act('begin_phase', ACTOR, sample_id='DNA01', phase_id=step['id'], intent_id=intent)
    if step['parameters'].get('duration_s'):
        flow.act('advance_time', ACTOR, seconds=step['parameters']['duration_s'])
    receipt = {'intent_id': intent,
               'actual_inputs': actual_inputs(flow, intent) if intent in flow.state['bookings'] else [],
               'actual_outputs': copy.deepcopy(step['fixture_actual_outputs']),
               'observations': observations(step), 'reason': REASON}
    if confirm: flow.act('confirm_phase', ACTOR, **receipt)
    return receipt


def extraction(flow, until=None):
    for step in flow.state['definition']['execution']['steps']:
        if step['id'] == until: return step
        phase(flow, step)


def ready_qc(flow):
    qc = flow.state['definition']['execution']['qc']
    flow.act('advance_time', ACTOR, seconds=qc['parameters']['buffer_equilibration_s'])
    flow.act('confirm_tapestation_ready', ACTOR,
             observations={**{key: True for key in qc['required_checks']},
                           'buffer_equilibration_s': qc['parameters']['buffer_equilibration_s']}, reason=REASON)


def prepare_qc(flow, role, *, confirm=True):
    qc = flow.state['definition']['execution']['qc']; intent = 'Unit.QC.' + role
    flow.act('begin_qc_preparation', ACTOR, role=role, intent_id=intent)
    params = qc['parameters']
    flow.act('advance_time', ACTOR, seconds=params['mix_duration_s'] + params['spin_duration_s'])
    receipt = {'intent_id': intent, 'actual_inputs': actual_inputs(flow, intent),
        'actual_outputs': copy.deepcopy(qc[role]['effect']['fixture_actual_outputs']),
        'observations': {'capped': True, 'mixed': True, 'spun_down': True,
            'mix_duration_s': params['mix_duration_s'], 'mix_rpm': params['mix_rpm'],
            'spin_duration_s': params['spin_duration_s']}, 'reason': REASON}
    if confirm: flow.act('confirm_qc_preparation', ACTOR, **receipt)
    return receipt


def request_qc(flow):
    qc = flow.state['definition']['execution']['qc']
    flow.act('begin_tapestation', ACTOR, instrument_run_id='Unit.TS.Run', analysis_id='Unit.TS.Analysis',
        measurement_id='Unit.TS.Measurement', screen_tape_id=qc['screen_tape_id'],
        lane_id=qc['sample']['lane_id'], ladder_lane_id=qc['ladder']['lane_id'])


def load_qc(flow):
    flow.act('confirm_tapestation_loaded', ACTOR, observations={**flow.expected_tapestation_loading(),
        'sample_loaded': True, 'ladder_loaded': True, 'identities_confirmed': True}, reason=REASON)


def complete_qc(flow):
    expected = flow.expected_tapestation()
    flow.act('confirm_tapestation_run_complete', ACTOR, observations={'run_complete': True, 'ladder_accepted': True,
        'instrument_run_id': expected['instrument_run_id'], 'analysis_id': expected['analysis_id']}, reason=REASON)


class DNeasyWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'exports').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='dneasy-unit-prefix-', dir=ROOT / 'exports')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder = Path(cls.temp.name)
        cls.prefix = cls.folder / 'extracted.sqlite3'
        with Journal(cls.prefix) as journal:
            flow = DNeasyWorkflow.create(journal, run_id=RUN)
            flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
            flow.act('workspace_clear', ACTOR, confirmed=True); flow.act('claim', ACTOR)
            extraction(flow); flow.close()
        cls.assay = cls.folder / 'assay.sqlite3'
        shutil.copyfile(cls.prefix, cls.assay)
        with Journal(cls.assay) as journal:
            flow = DNeasyWorkflow.open(journal, RUN)
            flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
            ready_qc(flow); prepare_qc(flow, 'ladder'); prepare_qc(flow, 'sample')
            request_qc(flow); load_qc(flow); complete_qc(flow); flow.close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.folder)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def open(self, mode='fresh', source=None):
        path = self.directory / (mode + '.sqlite3')
        if mode != 'fresh': shutil.copyfile(self.prefix if mode == 'extracted' else self.assay, path)
        journal = Journal(path); self.addCleanup(journal.close)
        if mode == 'fresh':
            flow = DNeasyWorkflow.create(journal, source=source, run_id=RUN)
            flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
            flow.act('workspace_clear', ACTOR, confirmed=True); flow.act('claim', ACTOR)
        else:
            flow = DNeasyWorkflow.open(journal, RUN)
            flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
        self.addCleanup(flow.close)
        return flow

    def import_report(self, flow, **changes):
        raw = synthetic_report(flow.expected_tapestation(), **changes)
        flow.act('import_results', ACTOR, artifact=raw, file_name='unit-fixture.json', origin='synthetic_export')
        return raw

    def dispositions(self, flow, *, abort=False):
        for identity, item in flow.state['inventory']['materials'].items():
            if item['disposition'] not in {'consumed', 'discarded'}:
                disposition = ('quarantined' if abort and item['kind'] == 'product' else
                               'retained' if item['kind'] in {'product', 'reagent', 'sample'} else 'discarded')
                flow.act('set_disposition', ACTOR, material_id=identity, disposition=disposition, reason=REASON)

    def test_fresh_root_has_only_selected_dna_input_and_canonical_inventory(self):
        flow = self.open(); state = flow.state
        samples = [item for item in state['inventory']['materials'].values() if item['kind'] == 'sample']
        self.assertEqual([item['id'] for item in samples], ['SYN.Source01.DNAAliquot'])
        self.assertNotIn('samples', state); self.assertNotIn('derived_vessels', state)
        self.assertEqual(state['process']['cursor'], 0)
        self.assertFalse(flow.report()['preparation_execution_ready'])
        with self.assertRaises(TaskError): MaterialWorkflow(flow.journal, RUN, flow.session)

    def test_order_and_generic_legacy_commands_cannot_bypass_phase_engine(self):
        flow = self.open(); before = flow.journal.history(RUN)
        with self.assertRaises(TaskError):
            flow.act('begin_phase', ACTOR, sample_id='DNA01', phase_id='spin_elute', intent_id='Skip')
        for command in ['begin_effect', 'confirm_effect', 'record_measurement', 'take', 'discard_import']:
            with self.subTest(command=command), self.assertRaises(TaskError): flow.act(command, ACTOR)
        self.assertEqual(flow.journal.history(RUN), before)

    def test_intent_precedes_effect_and_repeated_confirmation_does_not_book_twice(self):
        flow = self.open(); steps = flow.state['definition']['execution']['steps']
        phase(flow, steps[0]); receipt = phase(flow, steps[1], confirm=False)
        self.assertEqual(flow.state['bookings'][receipt['intent_id']]['outcome'], 'intent')
        self.assertEqual(flow.state['inventory']['materials']['SYN.Source01.DNAAliquot']['disposition'], None)
        flow.act('confirm_phase', ACTOR, **receipt)
        before = flow.journal.history(RUN)
        flow.act('confirm_phase', ACTOR, **receipt)
        self.assertEqual(flow.journal.history(RUN), before)
        self.assertEqual(flow.state['inventory']['materials']['SYN.Source01.DNAAliquot']['disposition'], 'consumed')
        changed = copy.deepcopy(receipt); changed['reason'] = 'Different observation'
        with self.assertRaises(TaskError): flow.act('confirm_phase', ACTOR, **changed)

    def test_pbs_dose_deviation_books_true_consumption_and_holds_irrevocably(self):
        flow = self.open(); steps = flow.state['definition']['execution']['steps']
        phase(flow, steps[0]); receipt = phase(flow, steps[1], confirm=False)
        pbs = next(item for item in receipt['actual_inputs'] if item['material_id'].endswith('.PBS'))
        pbs['quantity']['value'] = 1
        flow.act('confirm_phase', ACTOR, **receipt)
        state = flow.state
        self.assertEqual(state['bookings'][receipt['intent_id']]['outcome'], 'performed')
        self.assertEqual(next(item for item in state['bookings'][receipt['intent_id']]['actual_inputs']
                              if item['material_id'].endswith('.PBS'))['quantity']['value'], 1)
        self.assertTrue(state['process']['deviations']); self.assertIsNotNone(state['recovery_required'])
        flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
        with self.assertRaises(TaskError): phase(flow, steps[2])
        self.assertFalse(flow.report()['passed'])

    def test_unknown_reagent_actual_remains_unknown_and_quarantined(self):
        flow = self.open(); steps = flow.state['definition']['execution']['steps']
        phase(flow, steps[0]); receipt = phase(flow, steps[1], confirm=False)
        pbs = next(item for item in receipt['actual_inputs'] if item['material_id'].endswith('.PBS'))
        pbs['quantity']['value'] = None
        flow.act('confirm_phase', ACTOR, **receipt)
        material = flow.state['inventory']['materials'][pbs['material_id']]
        self.assertEqual(material['disposition'], 'quarantined')
        self.assertIsNone(ledger.remaining(flow.state, pbs['material_id'])['value'])
        self.assertTrue(flow.state['process']['deviations'])

    def test_process_only_phase_does_not_invent_material_consumption(self):
        flow = self.open(); step = flow.state['definition']['execution']['steps'][0]
        receipt = phase(flow, step)
        self.assertNotIn(receipt['intent_id'], flow.state['bookings'])
        self.assertEqual(flow.state['process']['cursor'], 1)

    def test_selected_rnase_branch_is_executed_and_booked_before_al_lysis(self):
        profile = json.loads(SOURCE.read_bytes()); profile['rnase_selected'] = True
        profile['reagent_aliquots']['RNaseA'] = {'material_id': 'SYN.Unit.RNaseA',
            'vessel_id': 'SYN.Unit.RNaseATube', 'quantity': {'value': 100, 'unit': 'uL'}}
        flow = self.open(source=profile)
        extraction(flow, until='add_al')
        state = flow.state
        self.assertEqual(state['process']['operations']['Unit.Phase.add_rnase']['state'], 'performed')
        self.assertEqual(state['process']['operations']['Unit.Phase.incubate_rnase']['state'], 'performed')
        self.assertLess(ledger.remaining(state, 'SYN.Unit.RNaseA')['value'], 100)
        self.assertEqual(state['definition']['execution']['steps'][state['process']['cursor']]['id'], 'add_al')

    def test_timed_phase_requires_explicit_clock_and_correct_temperature(self):
        flow = self.open(); step = extraction(flow, until='incubate_lysis')
        intent = 'Unit.Incubation'
        flow.act('begin_phase', ACTOR, sample_id='DNA01', phase_id=step['id'], intent_id=intent)
        receipt = {'intent_id': intent, 'actual_inputs': [], 'actual_outputs': [],
                   'observations': observations(step), 'reason': REASON}
        with self.assertRaises(TaskError): flow.act('confirm_phase', ACTOR, **receipt)
        flow.act('advance_time', ACTOR, seconds=step['parameters']['duration_s'])
        receipt['observations']['temperature_deg_c'] = 99
        with self.assertRaises(ObservationError): flow.act('confirm_phase', ACTOR, **receipt)
        self.assertEqual(flow.state['process']['phase_pending'], {'intent_id': intent})
        self.assertTrue(flow.state['process']['deviations'])

    def test_unknown_effect_restart_requires_explicit_resolution_and_inventory(self):
        flow = self.open(); steps = flow.state['definition']['execution']['steps']
        phase(flow, steps[0]); receipt = phase(flow, steps[1], confirm=False)
        flow.act('mark_effect_unknown', ACTOR, intent_id=receipt['intent_id'], reason=REASON)
        before = flow.state
        flow.close(); reopened = DNeasyWorkflow.open(flow.journal, RUN, resume=True)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.state['bookings'], before['bookings'])
        self.assertTrue(reopened.state['resources'])
        with self.assertRaises(TaskError): reopened.act('confirm_phase', ACTOR, **receipt)
        reopened.act('resolve_effect', ACTOR, outcome='performed', **receipt)
        self.assertEqual(reopened.state['process']['cursor'], 2)
        self.assertIsNotNone(reopened.state['recovery_required'])
        reopened.act('reconcile', ACTOR, observations=reopened.inventory_observations(), workspace_clear=True)
        phase(reopened, steps[2])

    def test_nonperformance_does_not_repeat_and_allows_controlled_abort(self):
        flow = self.open(); step = flow.state['definition']['execution']['steps'][0]
        receipt = phase(flow, step, confirm=False)
        flow.act('mark_effect_unknown', ACTOR, intent_id=receipt['intent_id'], reason=REASON)
        flow.act('resolve_effect', ACTOR, intent_id=receipt['intent_id'], outcome='not_performed', reason=REASON)
        flow.act('reconcile', ACTOR, observations=flow.inventory_observations(), workspace_clear=True)
        with self.assertRaises(TaskError): phase(flow, step, intent='SecondAttempt')
        flow.act('cancel', ACTOR, reason=REASON)
        self.dispositions(flow, abort=True)
        flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
        flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.assertEqual(flow.state['status'], 'cancelled')
        self.assertFalse(flow.report()['passed']); self.assertEqual(flow.state['resources'], [])

    def test_journal_failure_rolls_back_phase_cursor_ledger_and_intent(self):
        flow = self.open(); step = flow.state['definition']['execution']['steps'][0]
        before = flow.journal.history(RUN)
        with patch.object(flow.journal, 'append', side_effect=TaskError('Synthetic storage fault')):
            with self.assertRaises(TaskError): phase(flow, step, confirm=False)
        self.assertEqual(flow.journal.history(RUN), before)

    def test_extraction_preserves_fractions_without_inventing_dna_mass(self):
        flow = self.open('extracted'); state = flow.state
        product = state['definition']['execution']['samples']['DNA01']['product_material_id']
        self.assertEqual(state['inventory']['materials'][product]['kind'], 'product')
        self.assertEqual(ledger.remaining(state, product)['value'], 200)
        bound = state['inventory']['materials']['DNA01.bound_dna']
        self.assertEqual(bound['initial_quantity'], {'value': None, 'unit': 'ng'})
        for suffix in ['bind_flowthrough', 'aw1_flowthrough', 'aw2_flowthrough', 'column_residue']:
            self.assertEqual(state['inventory']['materials']['DNA01.' + suffix]['kind'], 'byproduct')
        self.assertFalse(flow.report()['passed'])

    def test_ladder_and_sample_preparations_have_separate_ancestry_and_consumption(self):
        flow = self.open('extracted'); ready_qc(flow)
        prepare_qc(flow, 'ladder'); prepare_qc(flow, 'sample'); state = flow.state
        qc = state['definition']['execution']['qc']
        sample_id = qc['sample']['effect']['outputs'][0]['material_id']
        ladder_id = qc['ladder']['effect']['outputs'][0]['material_id']
        product = state['definition']['execution']['samples']['DNA01']['product_material_id']
        self.assertIn(product, state['inventory']['materials'][sample_id]['parents'])
        self.assertNotIn(product, state['inventory']['materials'][ladder_id]['parents'])
        self.assertEqual(ledger.remaining(state, product)['value'], 199)
        self.assertNotEqual(state['inventory']['materials'][sample_id]['vessel_id'], state['inventory']['materials'][ladder_id]['vessel_id'])

    def test_wrong_qc_sample_dose_cannot_progress_or_release(self):
        flow = self.open('extracted'); ready_qc(flow)
        receipt = prepare_qc(flow, 'sample', confirm=False)
        receipt['actual_inputs'][0]['quantity']['value'] = 0.5
        flow.act('confirm_qc_preparation', ACTOR, **receipt)
        product = flow.state['definition']['execution']['samples']['DNA01']['product_material_id']
        self.assertEqual(ledger.remaining(flow.state, product)['value'], 199.5)
        self.assertTrue(flow.state['process']['deviations'])
        with self.assertRaises(TaskError): prepare_qc(flow, 'ladder')
        with self.assertRaises(TaskError): flow.act('release', ACTOR, workspace_clear=True)

    def test_missing_or_unknown_qc_mixture_volume_holds_before_loading(self):
        flow = self.open('extracted'); ready_qc(flow)
        receipt = prepare_qc(flow, 'sample', confirm=False)
        receipt['actual_outputs'][0]['quantity']['value'] = None
        flow.act('confirm_qc_preparation', ACTOR, **receipt)
        self.assertTrue(flow.state['process']['deviations'])
        self.assertIsNotNone(flow.state['recovery_required'])

    def test_assays_cannot_be_disposed_before_loading_or_during_manual_run(self):
        flow = self.open('extracted'); ready_qc(flow)
        prepare_qc(flow, 'ladder'); prepare_qc(flow, 'sample'); request_qc(flow)
        qc = flow.state['definition']['execution']['qc']
        for stage in ['before_load', 'loaded']:
            if stage == 'loaded': load_qc(flow)
            for role in ['sample', 'ladder']:
                with self.subTest(stage=stage, role=role), self.assertRaises(TaskError):
                    flow.act('set_disposition', ACTOR, material_id=qc[role]['effect']['outputs'][0]['material_id'],
                             disposition='discarded', reason=REASON)
        complete_qc(flow)
        with self.assertRaises(TaskError):
            flow.act('set_disposition', ACTOR, material_id=qc['sample']['effect']['outputs'][0]['material_id'],
                     disposition='discarded', reason=REASON)

    def test_loading_identity_mismatch_is_a_persisted_hold(self):
        flow = self.open('extracted'); ready_qc(flow)
        prepare_qc(flow, 'ladder'); prepare_qc(flow, 'sample'); request_qc(flow)
        mapping = flow.expected_tapestation_loading(); mapping['sample_vessel_id'] = 'WrongTube'
        with self.assertRaises(ObservationError):
            flow.act('confirm_tapestation_loaded', ACTOR, observations={**mapping,
                'sample_loaded': True, 'ladder_loaded': True, 'identities_confirmed': True}, reason=REASON)
        self.assertIsNone(flow.state['process']['qc']['loaded'])
        self.assertIsNotNone(flow.state['recovery_required'])

    def test_import_and_review_do_not_charge_the_eluate_twice(self):
        flow = self.open('assay'); before = copy.deepcopy(flow.state['bookings'])
        raw = self.import_report(flow)
        flow.act('review_tapestation', ACTOR, decision='accept', artifact_sha256=digest(raw), reason=REASON)
        self.assertEqual(flow.state['bookings'], before)
        self.assertEqual(flow.journal.artifact(digest(raw)), raw)
        self.assertEqual(ledger.remaining(flow.state, 'SYN.Source01.DNAExtract')['value'], 199)
        history = flow.journal.history(RUN)
        self.import_report(flow)
        self.assertEqual(flow.journal.history(RUN), history)

    def test_wrong_result_revision_is_preserved_but_quarantined(self):
        flow = self.open('assay'); wire = json.loads(synthetic_report(flow.expected_tapestation()))
        wire['rows'][0]['product_content_revision'] += 1
        raw = json.dumps(wire).encode()
        flow.act('import_results', ACTOR, artifact=raw, file_name='wrong.json', origin='synthetic_export')
        self.assertEqual(flow.state['imports'][digest(raw)]['status'], 'quarantined')
        self.assertEqual(flow.journal.artifact(digest(raw)), raw)
        with self.assertRaises(TaskError):
            flow.act('review_tapestation', ACTOR, decision='accept', artifact_sha256=digest(raw), reason=REASON)

    def test_qc_failure_does_not_become_accepted_biological_quality(self):
        flow = self.open('assay'); raw = self.import_report(flow, din=2.0)
        with self.assertRaises(TaskError):
            flow.act('review_tapestation', ACTOR, decision='accept', artifact_sha256=digest(raw), reason=REASON)
        flow.act('review_tapestation', ACTOR, decision='reject', artifact_sha256=digest(raw), reason=REASON)
        self.assertFalse(flow.report()['passed']); self.assertTrue(flow.state['process']['deviations'])

    def test_normal_release_retains_eluate_disposes_assays_and_keeps_limits(self):
        flow = self.open('assay'); raw = self.import_report(flow)
        flow.act('review_tapestation', ACTOR, decision='accept', artifact_sha256=digest(raw), reason=REASON)
        with self.assertRaises(TaskError): flow.act('release', ACTOR, workspace_clear=True)
        self.dispositions(flow)
        flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
        flow.act('release', ACTOR, workspace_clear=True)
        report = flow.report()
        self.assertTrue(report['passed']); self.assertEqual(report['resources'], [])
        self.assertEqual(report['inventory']['materials']['SYN.Source01.DNAExtract']['disposition'], 'retained')
        for flag in ['hardware_executed', 'network_executed', 'biochemical_protocol_executed',
                     'fragment_size_qualified', 'sop_qualified', 'tapestation_hardware_executed']:
            self.assertFalse(report[flag], flag)

    def test_abort_missing_receipt_keeps_resources_until_explicit_matching_observation(self):
        flow = self.open('assay')
        flow.act('cancel', ACTOR, reason=REASON)
        self.dispositions(flow, abort=True)
        flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
        before_resources = flow.state['resources']
        self.assertIn('instrument:TS01', before_resources)
        with self.assertRaises(TaskError): flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.assertEqual(flow.state['resources'], before_resources)
        expected = {**flow.expected_tapestation_abort(), 'instrument_stopped': True,
                    'sample_retrieved': True, 'ladder_retrieved': True,
                    'materials_accounted': True, 'identities_confirmed': True}
        wrong = {**expected, 'analysis_id': 'Wrong.Analysis'}
        with self.assertRaises(ObservationError):
            flow.act('confirm_tapestation_abort', ACTOR, observations=wrong, reason=REASON)
        self.assertIsNone(flow.state['process']['qc']['abort'])
        self.assertEqual(flow.state['resources'], before_resources)
        flow.act('confirm_tapestation_abort', ACTOR, observations=expected, reason=REASON)
        flow.act('confirm_inventory', ACTOR, observations=flow.inventory_observations())
        flow.act('finish_cancel', ACTOR, workspace_clear=True)
        self.assertEqual(flow.state['status'], 'cancelled')
        self.assertEqual(flow.state['resources'], [])
        self.assertFalse(flow.report()['passed'])


if __name__ == '__main__':
    unittest.main()
