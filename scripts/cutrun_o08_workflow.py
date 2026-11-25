"""Opt-in synthetic O08 evidence actions on the existing manual E4 journal."""

from collections import defaultdict
import copy

import cutrun_o08_results as results
import material_evidence
from cutrun_manual_recipe_v2_workflow import CutRunManualRecipeV2
from cutrun_preparation import require
from manual_tasks import TaskError, digest
from manual_workflow import text


class CutRunO08Workflow(CutRunManualRecipeV2):
    STEPS = (*CutRunManualRecipeV2.STEPS, 'bind_o08_plan', 'import_o08_export')

    @classmethod
    def _validate_format(cls, state):
        super()._validate_format(state)
        require(state['definition']['test_fixture_only'] is True, 'O08 imports require an E4 test-fixture run')

    def _artifact(self, state):
        raw = self._sonication_artifact
        require(isinstance(raw, bytes) and bool(raw), 'Original O08 fixture bytes required')
        require(state['observation_context']['artifact_sha256'] == digest(raw), 'O08 artifact checksum mismatch')
        return raw

    def _withdrawals(self, state, plan, stage):
        """Validate lineage and total allocated eluate against the root bookings."""
        allocated, prepared = defaultdict(float), set()
        for row in plan['positions']:
            if row['role'] == 'ntc':
                continue
            reaction = self._reaction(state, row['reaction_id'])
            material = state['inventory']['materials'].get(row['material_id'])
            require(reaction['role'] == row['role'] and reaction['current_material_id'] == row['material_id']
                    and material is not None and material['kind'] == 'product' and material['vessel_id'] == row['vessel_id'],
                    'O08 row needs the identified purified reaction product and vessel')
            identity = row['withdrawal_intent_id']
            action = state['manual']['actions'].get(identity, {})
            booking = state['bookings'].get(identity, {})
            require(action.get('operation') == 'qc_withdrawal' and action['method'] == plan['method']
                    and action['reaction_id'] == row['reaction_id'] and action['stage_run_id'] == stage['id']
                    and booking.get('outcome') == 'performed', 'O08 requires its own confirmed S11 QC withdrawal')
            actual, = booking['actual_inputs']
            quantity = actual['quantity']
            require(actual['material_id'] == material['id'] and quantity['unit'] == 'uL'
                    and quantity['value'] is not None, 'O08 requires the measured withdrawal of its product')
            if row['preparation_id'] not in prepared:
                prepared.add(row['preparation_id'])
                allocated[identity] += row['volumes']['eluate_ul']
            require(allocated[identity] <= quantity['value'] + 1e-9, 'O08 preparations exceed confirmed withdrawal')
        return set(allocated)

    def _bind_o08_plan(self, state, actor_id, file_name):
        text(file_name, 'O08 plan file name')
        raw = self._artifact(state)
        plan = results.read_plan(raw)
        checksum = digest(raw)
        require((plan['run_id'], plan['attempt_id']) == (state['run_id'], state['attempt_id']),
                'O08 plan belongs to a different run or attempt')
        plans = state['manual'].setdefault('o08_plans', {})
        plan_id = plan['plan_id']
        if plan_id in plans:
            require(plans[plan_id]['sha256'] == checksum, 'Bound O08 plan is immutable')
            return False
        self._stage_ready(state, 'S11')
        stage = self._require_stage(state, 'S11')
        for role, binding in plan['qc_bindings'].items():
            expected = state['definition']['manual_profile']['qc_plan']['roles'][role]
            require(plan['method'] in expected['methods']
                    and expected['assay_id'] in (None, binding['assay_id'])
                    and expected['evidence_ref'] in (None, binding['criteria_ref']),
                    'O08 plan must match the E4 QC role binding: ' + role)
        withdrawals = self._withdrawals(state, plan, stage)
        identity_fields = ('instrument_id', 'instrument_run_id', 'container_id')
        acquisition = tuple(plan['acquisition'][key] for key in identity_fields)
        for previous in plans.values():
            require(tuple(previous['plan']['acquisition'][key] for key in identity_fields) != acquisition,
                    'O08 acquisition already belongs to a bound plan')
            require(withdrawals.isdisjoint(previous['withdrawal_intent_ids']),
                    'O08 withdrawal already belongs to another plan')
        plans[plan_id] = {'sha256': checksum, 'file_name': file_name, 'plan': plan,
                          'withdrawal_intent_ids': sorted(withdrawals), 'stage_run_id': stage['id'],
                          'active_export_sha256': None, 'exports': {},
                          'binding': material_evidence.receipt(state, actor_id, 'Bound synthetic O08 plan')}

    def _quarantine(self, state, observed, checksum, reason):
        artifact = state['manual']['qc_artifacts'][checksum]
        artifact['status'] = 'quarantined'
        artifact.setdefault('rejections', []).append({'reason': reason, **material_evidence.provenance(state)})
        observed['status'], observed['error'] = 'quarantined', reason
        self._hold(state, 'quarantined_qc', reason)

    def _import_o08_export(self, state, actor_id, plan_id, file_name):
        text(plan_id, 'O08 plan identity')
        record = state['manual'].get('o08_plans', {}).get(plan_id)
        require(record is not None, 'Bind the synthetic O08 measurement plan first')
        raw = self._artifact(state)
        checksum = digest(raw)
        if checksum in record['exports']:
            return False
        stage = self._require_stage(state, 'S11')
        require(record['stage_run_id'] == stage['id'], 'O08 export belongs to another S11 stage')
        plan = record['plan']
        manual = state['manual']
        require(checksum not in manual['qc_artifacts'], 'O08 export already belongs to another evidence record')
        self._attach_qc(state, raw, file_name, origin='test_fixture')
        artifact = manual['qc_artifacts'][checksum]
        artifact['decoder'] = results.RESULTS[plan['method']]
        observed = {'status': 'archived', 'mapping_ids': [], 'result': None}
        record['exports'][checksum] = observed
        previous = record['active_export_sha256']
        try:
            normalized = results.normalize_export(raw, plan, record['sha256'])
            self._withdrawals(state, plan, stage)
            require(normalized['supersedes_sha256'] == previous,
                    'Reanalysis must name the current O08 export SHA-256')
            require(all(item['result'] is None or item['result']['analysis_revision'] != normalized['analysis_revision']
                        for item in record['exports'].values()), 'O08 analysis revision is already used')
        except (TaskError, OverflowError) as error:
            self._quarantine(state, observed, checksum, str(error))
            return

        observed['result'] = normalized
        if normalized['mapping_ready']:
            # Each file is a single evidence transaction. The shared mapper may
            # quarantine a row, in which case no partial mappings are committed.
            trial = copy.deepcopy(state)
            mappings = self._map_rows(trial, actor_id, normalized, plan['method'])
            trial_manual = trial['manual']
            trial_artifact = trial_manual['qc_artifacts'][checksum]
            if trial_artifact['status'] == 'quarantined':
                self._quarantine(state, observed, checksum, trial_artifact['rejections'][-1]['reason'])
                return
            manual['qc_bindings'] = trial_manual['qc_bindings']
            artifact['status'] = 'mapped'
            observed.update(status='mapped', mapping_ids=mappings)
        else:
            observed['status'] = 'incomplete' if not normalized['complete'] else 'needs_review'
            artifact['status'] = 'excluded'
        if previous is not None:
            prior = record['exports'][previous]
            prior['superseded_by'] = checksum
            manual['qc_artifacts'][previous]['status'] = 'excluded'
            for identity in prior['mapping_ids']:
                manual['qc_bindings'][identity]['invalidated'] = True
                manual['qc_reviews'].pop(identity, None)
        record['active_export_sha256'] = checksum

    def _map_rows(self, state, actor_id, result, method):
        acquisition = result['acquisition']
        checksum = result['original']['sha256']
        identifiers = []
        for row in result['rows']:
            identity = 'O08:' + checksum + ':' + row['id']
            volumes = row['volumes']
            dilution = None if volumes is None else volumes['prepared_ul'] / volumes['eluate_ul']
            binding = result['qc_bindings'][row['role']]
            self._map_qc(state, actor_id, identity, checksum, row['reaction_id'], row['material_id'], row['role'],
                         method, binding['assay_id'], acquisition['calibration_ref'] or acquisition['primer_id'],
                         row['locator'], row['result_status'], row['value'], row['unit'], dilution,
                         binding['criteria_ref'], row['reason'])
            if state['manual']['qc_artifacts'][checksum]['status'] == 'quarantined':
                break
            identifiers.append(identity)
        return identifiers

    def o08_report(self):
        trace = self.journal.history(self.run_id)
        state = trace[-1]['state']
        self._validate_format(state)
        self._audit_artifacts(trace)
        return {'format': 'solidcraftbot.cutrun-o08-synthetic-report/1', 'source_kind': 'test_fixture',
                'run_id': self.run_id, 'attempt_id': state['attempt_id'], 'execution_ready': False,
                'vendor_qc_decoder_executed': False, 'laboratory_bindings': None,
                'limits': None, 'laboratory_parameters': None, 'plans': state['manual'].get('o08_plans', {}),
                'fixture_open_requirements': state['definition']['open_requirements']}
