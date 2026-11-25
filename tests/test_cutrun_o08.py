"""O08 bind/import regressions using explicitly synthetic instrument originals."""

import copy
import json
from pathlib import Path
import unittest

import test_cutrun_manual_recipe_v2 as input_fixtures
from test_cutrun_manual_recipe_workflow import RecipeFixture

import cutrun_manual_recipe_v2_sources as v2_sources
from cutrun_manual_recipe_v2_workflow import CutRunManualRecipeV2
from cutrun_o08_results import normalize_export, read_plan
from cutrun_o08_workflow import CutRunO08Workflow
import material_ledger as ledger
from manual_tasks import TaskError, digest


FIXTURES = Path(__file__).parent / 'fixtures' / 'cutrun-o08'


def fixture(method, kind):
    return (FIXTURES / (method + '-' + kind + '.json')).read_bytes()


def encode(record):
    return json.dumps(record, allow_nan=False).encode()


class O08ResultTests(unittest.TestCase):
    def normalize(self, method, change=lambda export: None):
        raw = fixture(method, 'plan')
        export = json.loads(fixture(method, 'export'))
        change(export)
        return normalize_export(encode(export), read_plan(raw), digest(raw))

    def test_qpcr_uses_well_identity_and_keeps_cq_distinct_from_quantification(self):
        report = self.normalize('qpcr')
        rows = {row['id']: row for row in report['rows']}
        self.assertTrue(report['mapping_ready'])
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows['A01']['locator'], '/rows/11')
        self.assertEqual(rows['A01']['cq'], 20.1)
        self.assertEqual(rows['B01']['cq'], 37.1)
        self.assertIsNone(rows['B01']['value'])
        self.assertIsNone(rows['D01']['withdrawal_intent_id'])
        self.assertIsNone(rows['D01']['material_id'])
        self.assertIsNone(rows['D01']['cq'])

    def test_missing_well_and_positive_ntc_block_mapping(self):
        incomplete = self.normalize('qpcr', lambda export: export['rows'].pop())
        self.assertFalse(incomplete['complete'])
        self.assertFalse(incomplete['mapping_ready'])
        self.assertEqual(incomplete['rows'][0]['cq_status'], 'missing')

        def ntc(export):
            row = next(row for row in export['rows'] if row['id'] == 'D01')
            row.update(raw_cq='30.5', cq_status='determined', result_status='quantified', melt_status='target')

        report = self.normalize('qpcr', ntc)
        self.assertTrue(report['complete'])
        self.assertFalse(report['mapping_ready'])
        self.assertIn({'id': 'D01', 'code': 'ntc_requires_clarification'}, report['issues'])

    def test_rejects_duplicate_foreign_or_transplanted_results(self):
        changes = (
            (lambda x: x['rows'].append(x['rows'][0]), 'Foreign or duplicate'),
            (lambda x: x['rows'][0].update(id='Other.Well'), 'Foreign or duplicate'),
            (lambda x: x['rows'][0].update(preparation_id='Other.Aliquot'), 'preparation identity'),
            (lambda x: x.update(source_kind='device_export'), 'synthetic provenance'),
            (lambda x: x.update(plan_sha256='wrong'), 'bound plan'),
        )
        for change, expected in changes:
            with self.subTest(expected=expected), self.assertRaisesRegex(TaskError, expected):
                self.normalize('qpcr', change)

    def test_qubit_units_and_preparation_bases_apply_only_required_factors(self):
        report = self.normalize('qubit')
        rows = {row['role']: row for row in report['rows']}
        self.assertTrue(report['mapping_ready'])
        self.assertAlmostEqual(rows['h3k4me3']['value'], 2)
        self.assertEqual(rows['input']['value'], 4)
        self.assertIsNone(rows['igg']['value'])
        self.assertEqual(rows['input']['original_eluate_factors'], {
            'unit_to_ng_ul': 1, 'assay_to_prepared': 1, 'prepared_to_eluate': 1})

        def prepared(export):
            row = next(row for row in export['rows'] if row['id'].endswith('h3k4me3'))
            row.update(concentration=2500, concentration_basis='prepared_sample')

        self.assertEqual(self.normalize('qubit', prepared)['rows'][0]['value'], 5)

    def test_qubit_requires_standards_and_censors_above_range_without_inventing_a_value(self):
        with self.assertRaisesRegex(TaskError, 'both bound calibration standards'):
            self.normalize('qubit', lambda export: export['standards'].popitem())

        def above_range(export):
            row = next(row for row in export['rows'] if row['id'].endswith('input'))
            row.update(result_status='above_range', concentration=None, concentration_unit=None, flags=['High'])

        report = self.normalize('qubit', above_range)
        row = report['rows'][-1]
        self.assertEqual(row['flags'], ['High'])
        self.assertIsNone(row['value'])
        self.assertFalse(report['mapping_ready'])


class O08JournalTests(RecipeFixture, unittest.TestCase):
    InputFixture = input_fixtures.IntegratedInputTests
    setUp = InputFixture.setUp
    create = InputFixture.create
    seconds = InputFixture.seconds
    input_phase = InputFixture.input_phase
    move_input = InputFixture.move_input
    through_lysis = InputFixture.through_lysis
    begin_sonication = InputFixture.begin_sonication
    through_sonication = InputFixture.through_sonication
    withdraw = InputFixture.withdraw
    size = InputFixture.size

    def enter_s11(self):
        self.mode = 'test_fixture'
        self.through_sonication()
        self.withdraw()
        self.size()
        start = self.seconds()
        stage_id = self.stage_ids['S09', self.INPUT]
        following = self.flow.recipe_next(stage_id)
        intent = 'Test.O08.ClarifyInput'
        self.act('begin_recipe_operation', stage_run_id=stage_id, step_id=following['step_id'],
                 iteration=following['iteration'], operation='separate', intent_id=intent)
        self.clock.advance(10)
        self.act('confirm_recipe_operation', intent_id=intent, actual_inputs=[], actual_outputs=[],
                 observations={'performed': True, 'separated': True}, reason='Observed fixture clarification')
        self.input_phase(v2_sources.CLARIFICATION, 'Test.Sonicated', start, self.seconds(), 4)
        self.perform('S09', self.INPUT)
        self.finish('S09', self.INPUT)
        self.assertTrue(self.purify(self.INPUT))
        self.assertTrue(self.branch(self.REFERENCE))
        self.assertTrue(self.branch(self.IGG))
        self.begin('S11')
        self.flow = CutRunO08Workflow(self.journal, self.flow.run_id, self.flow.session, clock=self.clock)

    def plan_and_export(self, label):
        plan = json.loads(fixture(label, 'plan'))
        plan.update(run_id=self.flow.run_id, attempt_id=self.flow.state['attempt_id'])
        for role in plan['qc_bindings']:
            plan['qc_bindings'][role] = {'assay_id': 'Test.RawDNA.' + role, 'criteria_ref': 'decision_evidence'}
        reactions = {reaction['role']: (identity, reaction)
                     for identity, reaction in self.flow.state['manual']['reactions'].items()}
        prepared = set()
        for row in plan['positions']:
            if row['role'] == 'ntc':
                continue
            identity, reaction = reactions[row['role']]
            material_id = reaction['current_material_id']
            material = self.flow.state['inventory']['materials'][material_id]
            row.update(reaction_id=identity, material_id=material_id, vessel_id=material['vessel_id'])
            intent = row['withdrawal_intent_id']
            if intent not in prepared:
                amount = {'value': 2, 'unit': 'uL'}
                self.act('begin_qc_withdrawal', intent_id=intent, reaction_id=identity, method=plan['method'], quantity=amount)
                self.act('confirm_material_action', intent_id=intent,
                         actual_inputs=[{'material_id': material_id, 'quantity': amount}], actual_outputs=[],
                         reason='Observed fixture-only product withdrawal')
                self.stage_actions[self.stage_ids['S11', None]].append(intent)
                prepared.add(intent)
        export = json.loads(fixture(label, 'export'))
        export['plan_sha256'] = digest(encode(plan))
        return plan, export

    def import_result(self, plan, export):
        raw = encode(export)
        state = self.act('import_o08_export', plan_id=plan['plan_id'], file_name='fixture-export.json', artifact=raw)
        return state['manual']['o08_plans'][plan['plan_id']]['exports'][digest(raw)]

    def test_atomic_evidence_capture_review_and_reanalysis_preserve_withdrawals(self):
        self.enter_s11()
        qpcr_plan, qpcr = self.plan_and_export('qpcr')
        qubit_plan, qubit = self.plan_and_export('qubit')
        before = self.flow.state
        wrong = copy.deepcopy(qpcr_plan)
        for row in wrong['positions']:
            if row['role'] == 'h3k4me3':
                row['material_id'] = 'Foreign.Product'
        with self.assertRaisesRegex(TaskError, 'identified purified reaction product'):
            self.act('bind_o08_plan', file_name='foreign-plan.json', artifact=encode(wrong))
        for plan in (qpcr_plan, qubit_plan):
            raw = encode(plan)
            self.act('bind_o08_plan', file_name='fixture-plan.json', artifact=raw)
            self.assertEqual(self.journal.artifact(digest(raw)), raw)

        foreign = {**qpcr, 'plan_sha256': 'foreign'}
        rejected = self.import_result(qpcr_plan, foreign)
        rejected_sha256 = digest(encode(foreign))
        self.assertEqual(rejected['status'], 'quarantined')
        self.assertEqual(self.journal.artifact(rejected_sha256), encode(foreign))
        self.assertEqual(self.flow.state['recovery_required'], 'quarantined_qc')
        self.act('clarify_qc', artifact_sha256=rejected_sha256, decision='exclude', reason='Foreign fixture plan')
        self.act('resolve_deviation', hold_code='quarantined_qc', reason='Original fixture explicitly excluded',
                 evidence_ref='decision_evidence')
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                 reason='Confirmed fixture state after evidence exclusion')

        incomplete = {**qpcr, 'rows': qpcr['rows'][1:]}
        bad_checksum = digest(encode(incomplete))
        observed = self.import_result(qpcr_plan, incomplete)
        self.assertEqual(observed['status'], 'incomplete')
        self.assertEqual(observed['mapping_ids'], [])
        self.assertEqual(self.journal.artifact(bad_checksum), encode(incomplete))
        self.assertEqual(self.flow.state['manual']['qc_artifacts'][bad_checksum]['status'], 'excluded')
        self.assertEqual(self.flow.state['manual']['qc_bindings'], {})

        qpcr.update(analysis_revision='fixture/2', supersedes_sha256=bad_checksum)
        new_qpcr = self.import_result(qpcr_plan, qpcr)
        qubit_result = self.import_result(qubit_plan, qubit)
        self.assertEqual((len(new_qpcr['mapping_ids']), len(qubit_result['mapping_ids'])), (12, 3))
        self.assertEqual(self.flow.state['manual']['qc_reviews'], {})
        trace_size = len(self.journal.history(self.flow.run_id))
        self.assertEqual(self.import_result(qubit_plan, qubit), qubit_result)
        self.assertEqual(len(self.journal.history(self.flow.run_id)), trace_size)

        prior_mapping = new_qpcr['mapping_ids'][0]
        self.act('review_qc', mapping_id=prior_mapping, decision='technically_accepted', reason='Fixture review')
        qpcr.update(analysis_revision='fixture/3', supersedes_sha256=digest(encode(qpcr)))
        reanalysis = self.import_result(qpcr_plan, qpcr)
        state = self.flow.state
        self.assertTrue(state['manual']['qc_bindings'][prior_mapping]['invalidated'])
        self.assertNotIn(prior_mapping, state['manual']['qc_reviews'])
        self.assertEqual(self.journal.artifact(digest(encode(qpcr))), encode(qpcr))
        self.assertEqual(state['bookings'], before['bookings'])
        self.assertEqual(state['inventory'], before['inventory'])
        for identity in state['inventory']['materials']:
            self.assertEqual(ledger.remaining(state, identity), ledger.remaining(before, identity))
        report = self.flow.o08_report()
        self.assertFalse(report['execution_ready'])
        self.assertIsNone(report['laboratory_bindings'])
        self.assertEqual(report['plans'][qpcr_plan['plan_id']]['active_export_sha256'], digest(encode(qpcr)))

        mappings = reanalysis['mapping_ids'] + qubit_result['mapping_ids']
        # The original /2 entry point can review the extension's canonical QC mappings.
        self.flow = CutRunManualRecipeV2.open(self.journal, self.flow.run_id, resume=True, clock=self.clock)
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                 reason='Confirmed fixture state after reopening the journal')
        self.assertEqual(self.flow.state['bookings'], before['bookings'])
        for identity in mappings:
            self.act('review_qc', mapping_id=identity, decision='technically_accepted', reason='Fixture review')
        self.act('review_biology', mapping_ids=mappings, decision='accepted', criteria_ref='decision_evidence',
                 reason='Explicit fixture assessment')
        self.finish('S11')
        self.assertFalse(self.flow.report()['reference_success'])

    def test_real_observation_run_cannot_open_synthetic_extension(self):
        flow = self.create()
        with self.assertRaisesRegex(TaskError, 'test-fixture run'):
            CutRunO08Workflow(self.journal, flow.run_id, flow.session, clock=self.clock)


if __name__ == '__main__':
    unittest.main()
