"""S09 test-fixture observations on the existing SOP journal and material ledger.

Every sonication is one canonical same-vessel material transformation. Extra
fields bind its plan and evidence; they are not a second material balance or
an equipment controller. Only explicit test clocks and fixtures are accepted.
"""
import copy
import math

import material_evidence
import material_ledger as ledger
from cutrun_manual_sop_workflow import CutRunManualSopWorkflow
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ObservationError, text
import cutrun_input_sonication_sources as sources


class SnapshotClock:
    """Read an archived fixture without inventing elapsed wall time."""
    def __init__(self, record):
        self.record = copy.deepcopy(record)

    def sample(self):
        return copy.deepcopy(self.record)


class InputSonicationWorkflow(CutRunManualSopWorkflow):
    ENGINE = sources.ENGINE
    REPORT_FORMAT = 'solidcraftbot.cutrun-input-sonication-report/1'
    STEPS = (*CutRunManualSopWorkflow.STEPS, 'begin_sonication', 'confirm_sonication',
             'resolve_sonication', 'record_sonication_size')
    RECOVERY_COMMANDS = CutRunManualSopWorkflow.RECOVERY_COMMANDS | {
        'confirm_sonication', 'resolve_sonication', 'record_sonication_size', 'confirm_inventory'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    def __init__(self, journal, run_id, session, *, clock=None):
        if clock is None:
            clock = SnapshotClock(journal.state(run_id)[0]['clock']['last_sample'])
        super().__init__(journal, run_id, session, clock=clock)
        self._sonication_artifact = None

    @classmethod
    def _load_definition(cls, source, **kwargs):
        return sources.load(source, **kwargs)

    @classmethod
    def _extra_state(cls, definition, reactions):
        value = super()._extra_state(definition, reactions)
        identity = definition['runtime_profile']['bindings']['input_reaction_id']
        if definition['runtime_profile']['enabled']:
            if identity not in reactions or reactions[identity]['role'] != 'input':
                raise TaskError('Enabled sonication requires its actual separate Input reaction')
        return value

    @classmethod
    def _validate_format(cls, state):
        super()._validate_format(state)
        definition = state['definition']
        if (definition.get('test_fixture_only') is not True
                or definition.get('clock_source_kind') != 'test_clock'
                or definition.get('original_pdf_verified') is not False
                or definition.get('runtime_profile', {}).get('mode') != 'test_fixture_only'):
            raise TaskError('A separate test-only input-sonication definition is required')

    def act(self, command, actor_id, artifact=None, *, observation, **data):
        # A long-lived object must fence changed helpers before even recording
        # a new clock observation or rejected command.
        self._verify_runtime(self.state)
        self._verify_initial_artifacts(self.journal, self.state)
        self._sonication_artifact = artifact
        try:
            return super().act(command, actor_id, artifact=artifact, observation=observation, **data)
        finally:
            self._sonication_artifact = None

    @staticmethod
    def _enabled(state):
        return state['definition']['runtime_profile']['enabled'] is True

    @staticmethod
    def _intents(state):
        return {identity: action['sonication'] for identity, action in state['manual']['actions'].items()
                if 'sonication' in action}

    @staticmethod
    def _device(state):
        return state['definition']['sonication_plan']['parameters']['device_instance_id']['value']

    @classmethod
    def _resources(cls, state):
        result = set(super()._resources(state))
        if not cls._enabled(state):
            return sorted(result)
        device = cls._device(state)
        if device is not None:
            pending = any(state['bookings'][identity]['outcome'] in {'intent', 'unknown'}
                          for identity in cls._intents(state))
            present = any(vessel['location'].get('kind') == 'logical'
                          and vessel['location'].get('holder_id') == device
                          for vessel in state['inventory']['vessels'].values())
            if pending or present:
                result.add('sonicator:' + device)
        return sorted(result)

    def _confirm_inventory(self, state, actor_id, observations):
        super()._confirm_inventory(state, actor_id, observations)
        state['resources'] = self._resources(state)

    def _after_transition(self, state, command, actor_id, data, *, rejected=False):
        super()._after_transition(state, command, actor_id, data, rejected=rejected)
        state['resources'] = ([] if state['status'] in {'completed', 'cancelled'}
                              else self._resources(state))

    @staticmethod
    def _origin(state, vessel_id):
        declared = next((item for item in state['definition']['initial_vessels']
                         if item['id'] == vessel_id), None)
        if declared is None or declared['location']['kind'] != 'rack':
            raise TaskError('The sonication fixture requires an original identified rack place')
        return copy.deepcopy(declared['location'])

    def _original(self, state, actor_id, label):
        checksum = state['observation_context']['artifact_sha256']
        if checksum is None:
            raise TaskError('An immutable original artifact is required for sonication evidence')
        if self._sonication_artifact is not None:
            if digest(self._sonication_artifact) != checksum:
                raise TaskError('Sonication evidence original checksum mismatch')
            if (checksum not in state['definition']['initial_artifact_sha256']
                    and checksum not in state['sop']['artifacts']):
                state['sop']['artifacts'][checksum] = {'file_name': label, 'origin': 'test_fixture',
                    'receipt': material_evidence.receipt(state, actor_id, 'Fixture sonication original')}
        else:
            self._owned_original(state, checksum)
        return checksum

    def _begin_material_action(self, state, actor_id, intent_id, reaction_id, stage_id, **kwargs):
        tagged = None
        if self._enabled(state) and stage_id == 'S09':
            if kwargs.get('kind') != 'withdrawal' or kwargs.get('outputs') != []:
                raise TaskError('Use begin_sonication for the S09 transformation')
            current = self._reaction(state, reaction_id)['current_material_id']
            tagged = next((identity for identity, item in self._intents(state).items()
                if item['reaction_id'] == reaction_id and item['material_after_id'] == current
                and state['bookings'][identity]['outcome'] == 'performed'), None)
            if tagged is None:
                raise TaskError('S09 QC withdrawal must follow its confirmed sonication')
        changed = super()._begin_material_action(state, actor_id, intent_id, reaction_id, stage_id, **kwargs)
        if tagged is not None and changed is not False:
            meta = self._intents(state)[tagged]
            state['manual']['actions'][intent_id]['sonication_qc'] = {
                'sonication_intent_id': tagged, 'material_id': meta['material_after_id'],
                'vessel_id': meta['vessel_id'], 'stage_run_id': meta['stage_run_id']}
        return changed

    def _confirm_material_action(self, state, actor_id, intent_id, actual_inputs, actual_outputs, reason):
        if intent_id in self._intents(state):
            raise TaskError('Use confirm_sonication or resolve_sonication for this effect')
        return super()._confirm_material_action(state, actor_id, intent_id, actual_inputs, actual_outputs, reason)

    def _begin_sonication(self, state, actor_id, intent_id, reaction_id, stage_run_id, output_material_id, reason):
        text(reason, 'fixture sonication intent reason')
        if not self._enabled(state):
            raise TaskError('Optional input sonication is disabled')
        old = self._intents(state).get(intent_id)
        if old is not None:
            if ((old['reaction_id'], old['stage_run_id'], old['material_after_id'])
                    != (reaction_id, stage_run_id, output_material_id)
                    or state['bookings'][intent_id]['request']['purpose'] != reason):
                raise TaskError('Conflicting repeated sonication intent')
            return False
        plan = state['definition']['sonication_plan']
        if not plan['planning_complete']:
            raise TaskError('Synthetic sonication plan fields remain open')
        binding = state['definition']['runtime_profile']['bindings']
        reaction = self._reaction(state, reaction_id)
        if reaction_id != binding['input_reaction_id'] or reaction['role'] != 'input':
            raise ObservationError('Sonication belongs exclusively to the bound Input reaction')
        stage = self._require_stage(state, 'S09', reaction_id)
        if stage['id'] != stage_run_id:
            raise ObservationError('Sonication stage-run identity mismatch')
        material_id = reaction['current_material_id']
        material = state['inventory']['materials'][material_id]
        vessel_id = material['vessel_id']
        if material['kind'] != 'intermediate' or vessel_id is None:
            raise TaskError('S09 sonication requires its current prepared intermediate')
        if (stage['material_id'], stage['vessel_id']) != (material_id, vessel_id):
            raise ObservationError('Sonication differs from the current stage material/vessel')
        expected = {'kind': 'logical', 'holder_id': self._device(state),
                    'place_id': binding['sonicator_place_id']}
        if state['inventory']['vessels'][vessel_id]['location'] != expected:
            raise ObservationError('Observe the bound input vessel at the declared sonicator place first')
        amount = ledger.remaining(state, material_id)
        if amount['unit'] != 'uL':
            raise TaskError('Sonication input quantity must use explicit uL')
        fill = plan['parameters']['fill_volume_ul']['value']
        if amount['value'] is not None and not math.isclose(amount['value'], fill, abs_tol=1e-9, rel_tol=0):
            raise ObservationError('Declared fixture fill differs from the current root quantity')
        origin = self._origin(state, vessel_id)
        inputs = [{'material_id': material_id,
                   'quantity': {'value': amount['value'], 'unit': 'uL'}, 'consume_all': True}]
        outputs = [{'material_id': output_material_id, 'kind': 'intermediate',
                    'vessel_id': vessel_id, 'role': 'sonicated_input'}]
        super()._begin_material_action(state, actor_id, intent_id, reaction_id, 'S09',
            kind='transformation', inputs=inputs, outputs=outputs, purpose=reason,
            retained_material_id=output_material_id)
        state['manual']['actions'][intent_id]['sonication'] = {
            'reaction_id': reaction_id, 'stage_run_id': stage_run_id,
            'material_before_id': material_id, 'material_after_id': output_material_id,
            'vessel_id': vessel_id, 'quantity_before': copy.deepcopy(inputs[0]['quantity']),
            'original_rack_location': origin, 'intent_session': state['session'],
            'pulse_plan': copy.deepcopy(plan['pulse_plan']), 'size_records': {},
            'physical_receipt': None,
            'source_pins_sha256': digest(encoded(state['definition']['source_files_sha256']).encode())}
        state['resources'] = self._resources(state)

    def _sonication(self, state, intent_id):
        value = self._intents(state).get(intent_id)
        if value is None:
            raise TaskError('Unknown canonical sonication intent')
        return value

    def _confirm_sonication(self, state, actor_id, intent_id, actual_output_quantity, observed_vessel_id, reason):
        meta = self._sonication(state, intent_id)
        if observed_vessel_id != meta['vessel_id']:
            raise ObservationError('Observed sonication vessel identity mismatch')
        quantity = ledger.quantity(actual_output_quantity, zero=True)
        if quantity['unit'] != 'uL':
            raise TaskError('Observed sonication output needs explicit uL')
        checksum = self._original(state, actor_id, 'sonication-physical-receipt')
        physical = {'observed_vessel_id': observed_vessel_id, 'actual_output_quantity': quantity,
                    'artifact_sha256': checksum, 'reason': reason}
        if state['bookings'][intent_id]['outcome'] == 'performed':
            if meta['physical_receipt']['observation'] != physical:
                raise TaskError('Conflicting repeated physical sonication receipt')
            return False
        inputs = [{'material_id': meta['material_before_id'], 'quantity': copy.deepcopy(meta['quantity_before'])}]
        outputs = [{'material_id': meta['material_after_id'], 'quantity': quantity}]
        super()._confirm_material_action(state, actor_id, intent_id, inputs, outputs, reason)
        # The canonical ledger commits an atomic cloned proposal, replacing
        # nested dictionaries. Reacquire metadata from that authoritative state.
        meta = self._sonication(state, intent_id)
        meta['physical_receipt'] = {'observation': physical,
            'receipt': material_evidence.receipt(state, actor_id, reason),
            'captured_at': copy.deepcopy(state['clock']['last_sample'])}
        state['resources'] = self._resources(state)

    def _resolve_sonication(self, state, actor_id, intent_id, outcome, reason,
                            actual_output_quantity=None, observed_vessel_id=None):
        self._sonication(state, intent_id)
        if outcome == 'performed':
            if actual_output_quantity is None or observed_vessel_id is None:
                raise TaskError('Performed resolution needs observed output and vessel')
            return self._confirm_sonication(state, actor_id, intent_id, actual_output_quantity,
                                            observed_vessel_id, reason)
        if actual_output_quantity is not None or observed_vessel_id is not None:
            raise TaskError('Only a performed resolution has output observations')
        if outcome == 'unknown':
            return self._mark_unknown(state, actor_id, intent_id, reason)
        if outcome != 'not_performed':
            raise TaskError('Explicit sonication resolution outcome required')
        return super()._resolve_action(state, actor_id, intent_id, 'not_performed', [], [], False, reason)

    def _record_sonication_size(self, state, actor_id, intent_id, size_id, withdrawal_intent_id,
                                minimum_bp, maximum_bp, reason):
        meta = self._sonication(state, intent_id)
        text(size_id, 'size evidence identity')
        if state['bookings'][intent_id]['outcome'] != 'performed':
            raise TaskError('Size evidence requires a confirmed physical sonication effect')
        for value in (minimum_bp, maximum_bp):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise TaskError('Finite positive bp observations required')
        if minimum_bp > maximum_bp:
            raise TaskError('Ordered fragment-size interval required')
        action = state['manual']['actions'].get(withdrawal_intent_id)
        booking = state['bookings'].get(withdrawal_intent_id)
        expected = {'sonication_intent_id': intent_id, 'material_id': meta['material_after_id'],
                    'vessel_id': meta['vessel_id'], 'stage_run_id': meta['stage_run_id']}
        if (action is None or action.get('sonication_qc') != expected or booking is None
                or booking['outcome'] != 'performed' or booking['request']['kind'] != 'withdrawal'
                or len(booking['actual_inputs']) != 1
                or booking['actual_inputs'][0]['material_id'] != meta['material_after_id']):
            raise ObservationError('Size evidence requires its own confirmed root QC withdrawal')
        amount = booking['actual_inputs'][0]['quantity']
        if amount['unit'] != 'uL' or amount['value'] is None or amount['value'] <= 0:
            raise TaskError('QC consumption must be explicitly observed, not unknown or zero')
        checksum = self._original(state, actor_id, 'sonication-fragment-size-original')
        record = {'size_id': size_id, 'withdrawal_intent_id': withdrawal_intent_id,
            'material_id': meta['material_after_id'], 'vessel_id': meta['vessel_id'],
            'minimum_bp': minimum_bp, 'maximum_bp': maximum_bp, 'unit': 'bp',
            'artifact_sha256': checksum, 'reason': reason}
        old = meta['size_records'].get(size_id)
        if old is not None:
            if old['observation'] != record:
                raise TaskError('Size evidence identity reused with different content')
            return False
        target = state['definition']['sonication_plan']['fragment_size']
        comparison = target['comparison_target'];column = target['column_maximum_exclusive_bp']['value']
        conforms = minimum_bp >= comparison['minimum'] and maximum_bp <= comparison['maximum']
        conforms &= column is None or maximum_bp < column
        meta['size_records'][size_id] = {'observation': record, 'fixture_range_conformant': conforms,
            'biological_acceptance': False, 'receipt': material_evidence.receipt(state, actor_id, reason)}
        if not conforms:
            self._hold(state, 'sonication_size_deviation', size_id + ': fixture comparison/column interval failed')

    def _sonication_issues(self, state, stage):
        if stage['stage_id'] != 'S09' or not self._enabled(state):
            return []
        items = [(identity, item) for identity, item in self._intents(state).items()
                 if item['stage_run_id'] == stage['id']]
        performed = [(identity, item) for identity, item in items
                     if state['bookings'][identity]['outcome'] == 'performed']
        issues = []
        if len(performed) != 1:
            issues.append('exactly_one_confirmed_sonication_required')
        for identity, meta in performed:
            if meta['physical_receipt'] is None:
                issues.append('physical_sonication_original_required')
            records = list(meta['size_records'].values())
            if not records or not all(item['fixture_range_conformant'] for item in records):
                issues.append('identified_fragment_size_evidence_required')
            phase = super()._phase_assessment(state, stage, 'S09.input_preparation')
            duration = phase.get('duration_bounds', {}).get('min_s')
            nominal = meta['pulse_plan']['nominal_elapsed_s']
            if duration is None or nominal is None or duration < nominal:
                issues.append('pulse_plan_exceeds_observed_phase_duration')
            selected_id = phase.get('selected_time_evidence_id')
            selected = next((item for item in stage['phases']['S09.input_preparation']['times']
                             if item['evidence_id'] == selected_id), None)
            if selected is not None:
                action = state['manual']['actions'][identity]
                beginning = action['recorded_intent_at']
                ending = None if meta['physical_receipt'] is None else meta['physical_receipt']['captured_at']
                if selected['time_basis_id'] == beginning['clock_id']:
                    earliest = selected['start_earliest_s']
                    if earliest is None or earliest < beginning['monotonic_ns'] / 1_000_000_000:
                        issues.append('sonication_time_predates_effect_intent')
                if ending is not None and selected['time_basis_id'] == ending['clock_id']:
                    latest = selected['end_latest_s']
                    uncertainty = ending['uncertainty_s']
                    if (latest is None or uncertainty is None
                            or latest > ending['monotonic_ns'] / 1_000_000_000 + uncertainty):
                        issues.append('sonication_time_follows_physical_receipt')
        return issues

    def _stage_assessment(self, state, stage):
        result = super()._stage_assessment(state, stage)
        result['issues'].extend(self._sonication_issues(state, stage))
        result['conformant'] = not result['issues']
        return result

    def _complete_stage(self, state, actor_id, stage_run_id, receipts, action_ids, reason):
        stage = self._stage(state, stage_run_id)
        if stage['stage_id'] == 'S09' and self._enabled(state):
            required = set()
            for identity, meta in self._intents(state).items():
                if meta['stage_run_id'] != stage_run_id or state['bookings'][identity]['outcome'] != 'performed':
                    continue
                required.add(identity)
                required.update(item['observation']['withdrawal_intent_id'] for item in meta['size_records'].values())
                if state['inventory']['vessels'][meta['vessel_id']]['location'] != meta['original_rack_location']:
                    raise ObservationError('Observe return to the original rack before completing S09')
            if not required or not required <= set(action_ids):
                raise TaskError('S09 must link its canonical sonication and size-QC withdrawal receipts')
        super()._complete_stage(state, actor_id, stage_run_id, receipts, action_ids, reason)
        if stage['stage_id'] == 'S09':
            stage['completion']['sonication_return_receipt'] = copy.deepcopy(state['inventory_confirmation'])

    def _restored(self, state):
        if self._enabled(state):
            if any(vessel['location'].get('kind') == 'logical'
                   and vessel['location'].get('holder_id') == self._device(state)
                   for vessel in state['inventory']['vessels'].values()):
                raise ObservationError('The declared sonicator place remains occupied')
            vessels = {item['vessel_id'] for item in self._intents(state).values()}
            reaction_id = state['definition']['runtime_profile']['bindings']['input_reaction_id']
            if reaction_id in state['manual']['reactions']:
                vessels.add(state['manual']['reactions'][reaction_id]['vessel_id'])
            for vessel_id in vessels:
                if state['inventory']['vessels'][vessel_id]['location'] != self._origin(state, vessel_id):
                    raise ObservationError('Return the input vessel to its original rack before handover')
        return super()._restored(state)

    def _report(self, state, trace):
        report = super()._report(state, trace)
        intents = {}
        for identity, item in self._intents(state).items():
            intents[identity] = {**copy.deepcopy(item), 'booking_outcome': state['bookings'][identity]['outcome'],
                'continuation_uncertain': (state['bookings'][identity]['outcome'] in {'intent', 'unknown'}
                    and item['intent_session'] != state['session'])}
        report.update(mode='test_fixture_only', stage_readiness=copy.deepcopy(state['definition']['real_stage_readiness']),
            preparation_complete=False, execution_ready=False, reference_success=False,
            synthetic_gate_readiness=copy.deepcopy(state['definition']['synthetic_gate_readiness']))
        report['sonication'] = {'enabled': self._enabled(state), 'mode': 'test_fixture_only',
            'test_fixture_only': True, 'intents': intents,
            'pending_intents': [identity for identity in intents if intents[identity]['booking_outcome'] in {'intent', 'unknown'}],
            'source_pins': copy.deepcopy(state['definition']['source_files_sha256']),
            'raw_open_requirements': copy.deepcopy(state['definition']['raw_open_requirements']),
            'flags': {'hardware_executed': False, 'network_executed': False, 'ros_executed': False,
                      'robot_motion_executed': False, 'biological_acceptance': False}}
        return report
