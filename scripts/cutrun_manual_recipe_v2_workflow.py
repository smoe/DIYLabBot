"""Manual recipe /2 combines the existing effect handlers at one material root."""

import copy

import cutrun_manual_recipe_v2_sources as sources
import material_ledger as ledger
from cutrun_input_sonication_workflow import InputSonicationWorkflow, SnapshotClock
from cutrun_manual_recipe_workflow import CutRunManualRecipeWorkflow
from cutrun_manual_sop_workflow import CutRunManualSopWorkflow
from manual_tasks import TaskError, digest
from manual_workflow import ObservationError
from material_workflow import MaterialWorkflow


EXTRACTION = 'S09.input_extraction_addition'
CLARIFICATION = 'S09.clarified_fraction'
LYSIS_MIXTURE = 'input_lysis_mixture'
LATE_INPUT_ROLES = {LYSIS_MIXTURE, 'input_lysate', 'sonicated_input', 'clarified_input_supernatant', 'input_debris'}


class CutRunManualRecipeV2(CutRunManualRecipeWorkflow, InputSonicationWorkflow):
    ENGINE = sources.ENGINE
    REPORT_FORMAT = 'solidcraftbot.cutrun-manual-recipe-report/2'
    STEPS = tuple(dict.fromkeys((*CutRunManualRecipeWorkflow.STEPS, *InputSonicationWorkflow.STEPS)))
    RECOVERY_COMMANDS = CutRunManualRecipeWorkflow.RECOVERY_COMMANDS | InputSonicationWorkflow.RECOVERY_COMMANDS
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    def __init__(self, journal, run_id, session, *, clock=None):
        state = journal.state(run_id)[0]
        self._validate_format(state)
        if clock is None:
            if session is None or state['definition']['test_fixture_only']:
                clock = SnapshotClock(state['clock']['last_sample'])
            else:
                from manual_process_clock import SystemClock
                clock = SystemClock()
        super().__init__(journal, run_id, session, clock=clock)
        self._resolving_sonication = False

    @classmethod
    def _load_definition(cls, source, **kwargs):
        return sources.load(source, **kwargs)

    @classmethod
    def _validate_reagent_binding(cls, inventory, source, reaction_id, item, key):
        selected = sources.selection(source)
        return super()._validate_reagent_binding(inventory, {
            name: selected[name] for name in ('base_profile', 'sop_profile', 'recipe_profile')
        }, reaction_id, item, key)

    @classmethod
    def _extra_state(cls, definition, reactions):
        # An archive can be created with an open input binding. S09 stays gated
        # until a new, complete definition is created with its actual IDs.
        binding = definition['runtime_profile']['bindings']['input_reaction_id']
        if binding is None:
            definition = {**definition, 'runtime_profile': {**definition['runtime_profile'], 'enabled': False}}
        return super()._extra_state(definition, reactions)

    @classmethod
    def _validate_format(cls, state):
        MaterialWorkflow._validate_format.__func__(cls, state)
        definition = state['definition']
        mode = definition.get('runtime_profile', {}).get('mode')
        if (definition.get('runtime_engine') != cls.ENGINE
                or definition.get('format') != 'solidcraftbot.material-workflow-definition/3'
                or definition.get('profile', {}).get('type') != CutRunManualRecipeWorkflow.ENGINE
                or any(state.get(section, {}).get('engine') != cls.ENGINE for section in ('manual', 'sop', 'recipe'))
                or definition.get('sop_profile', {}).get('format') != sources.PROFILE_FORMAT
                or definition.get('sop_protocol', {}).get('format') != sources.PROTOCOL_FORMAT
                or mode not in sources.MODES or definition.get('clock_source_kind') != sources.MODES[mode]
                or definition.get('test_fixture_only') is not (mode == 'test_fixture')):
            raise TaskError('Matching consolidated recipe, phase and clock contracts required')

    def act(self, command, actor_id, artifact=None, *, observation, **data):
        fixture = self.state['definition']['test_fixture_only']
        if isinstance(observation, dict) and (observation.get('source_kind') == 'test_fixture') != fixture:
            raise TaskError('Fixture and real observations cannot be mixed')
        if command in {'attach_sop_evidence', 'attach_qc', 'import_results'}:
            if (data.get('origin') == 'test_fixture') != fixture:
                raise TaskError('Original provenance must match the selected mode')
        return super().act(command, actor_id, artifact=artifact, observation=observation, **data)

    def _original(self, state, actor_id, label):
        context = state['observation_context']
        checksum = context['artifact_sha256']
        if not checksum:
            raise TaskError('Own original evidence bytes are required')
        if self._sonication_artifact is not None:
            if digest(self._sonication_artifact) != checksum:
                raise TaskError('Sonication evidence original checksum mismatch')
            origin = {'test_fixture': 'test_fixture', 'human_observation': 'operator_transcription',
                      'device_export': 'device_original', 'external_record': 'external_record'}[context['source_kind']]
            self._attach_sop_evidence(state, actor_id, label, origin)
        elif checksum in state['sop']['artifacts']:
            self._owned_original(state, checksum)
        else:
            raise TaskError('Attach the original evidence to this run before citing it')
        return checksum

    @staticmethod
    def _input_effect(state, stage, step, operation):
        return next((item for item in state['recipe']['operations'].values()
                     if item['stage_run_id'] == stage['id'] and item.get('step_id') == step
                     and item.get('operation') == operation and item['outcome'] == 'performed'), None)

    def _begin_recipe_operation(self, state, actor_id, stage_run_id, step_id, iteration, operation, intent_id,
                                outputs=None, retained_material_id=None, source_quantity=None):
        stage = self._stage(state, stage_run_id)
        declared = [out for out in (outputs or []) if isinstance(out, dict)]
        if stage['stage_id'] == 'S02' and any(out.get('role') in LATE_INPUT_ROLES for out in declared):
            raise TaskError('S02 prepares the Input; lysate and sonicated material belong to S09')
        if step_id == EXTRACTION and operation == 'add':
            if len(declared) != 1 or declared[0].get('role') != LYSIS_MIXTURE:
                raise TaskError('S09 extraction addition must retain the identified input lysis mixture')
        if step_id == CLARIFICATION:
            if (stage['stage_id'] != 'S09' or self._sonication_issues(state, stage)
                    or not self._phase_assessment(state, stage, sources.SONICATION)['conformant']):
                raise TaskError('Clarification requires the confirmed sonication and its identified size evidence')
            sonication = self._performed_sonication(state, stage)
            current = self._reaction(state, stage['reaction_id'])['current_material_id']
            if current != sonication['material_after_id']:
                raise ObservationError('Clarification must consume the sonicated Input lineage')
            if operation == 'remove' and not self._phase_assessment(state, stage, sources.CLARIFICATION)['conformant']:
                raise TaskError('Qualified clarification time and temperature coverage required before fraction removal')
        result = super()._begin_recipe_operation(state, actor_id, stage_run_id, step_id, iteration,
                                                  operation, intent_id, outputs, retained_material_id, source_quantity)
        if result is not False and step_id in {EXTRACTION, CLARIFICATION}:
            state['recipe']['operations'][intent_id]['captured_intent_at'] = copy.deepcopy(state['clock']['last_sample'])
        return result

    def _confirm_recipe_operation(self, state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason):
        result = super()._confirm_recipe_operation(state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason)
        item = state['recipe']['operations'][intent_id]
        if result is not False and item['outcome'] == 'performed' and item['step_id'] in {EXTRACTION, CLARIFICATION}:
            item['captured_receipt_at'] = copy.deepcopy(state['clock']['last_sample'])
        return result

    def _performed_sonication(self, state, stage):
        return next((item for identity, item in self._intents(state).items()
                     if item['stage_run_id'] == stage['id'] and state['bookings'][identity]['outcome'] == 'performed'), None)

    @staticmethod
    def _identity(stage, phase_id):
        identity = CutRunManualSopWorkflow._identity(stage, phase_id)
        subject = stage.get('phase_subjects', {}).get(phase_id)
        return identity if subject is None else {**identity, **subject}

    def _record_phase(self, state, actor_id, stage_run_id, phase_id, record, kind):
        if phase_id in sources.PHASES:
            stage = self._stage(state, stage_run_id)
            if stage['stage_id'] != 'S09':
                raise TaskError('Input lysis, sonication and clarification belong to S09')
            mixed = self._input_effect(state, stage, EXTRACTION, 'mix')
            sonic = self._performed_sonication(state, stage)
            if mixed is None or phase_id != sources.LYSIS and sonic is None:
                raise TaskError('Record the recipe mixture and the phase-specific material effect first')
            lower, upper = mixed['captured_receipt_at'], None
            subject = mixed['target_material_id']
            if phase_id == sources.SONICATION:
                subject = sonic['material_before_id']
            elif phase_id == sources.CLARIFICATION:
                separate = self._input_effect(state, stage, CLARIFICATION, 'separate')
                if separate is None:
                    raise TaskError('Confirm the clarification observation before its interval evidence')
                subject = sonic['material_after_id']
                lower, upper = separate['captured_intent_at'], separate['captured_receipt_at']
            material = state['inventory']['materials'][subject]
            vessel = (sonic['vessel_id'] if sonic is not None else material['vessel_id'])
            stage.setdefault('phase_subjects', {})[phase_id] = {'material_id': subject, 'vessel_id': vessel}
            if kind == 'times' and isinstance(record, dict):
                if record.get('time_basis_id') == lower['clock_id']:
                    start = record.get('start_earliest_s')
                    if type(start) in (int, float) and start < lower['monotonic_ns'] / 1e9:
                        raise TaskError('An observed phase cannot predate its associated preparation or intent')
                if upper and upper['uncertainty_s'] is not None and record.get('time_basis_id') == upper['clock_id']:
                    end = record.get('end_latest_s')
                    if type(end) in (int, float) and end > upper['monotonic_ns'] / 1e9 + upper['uncertainty_s']:
                        raise TaskError('An observed clarification interval cannot follow its receipt')
        return super()._record_phase(state, actor_id, stage_run_id, phase_id, record, kind)

    def _begin_sonication(self, state, actor_id, intent_id, reaction_id, stage_run_id, output_material_id, reason):
        if intent_id not in self._intents(state):
            stage = self._require_stage(state, 'S09', reaction_id)
            if (stage['id'] != stage_run_id or self._reaction(state, reaction_id)['role'] != 'input'
                    or self._performed_sonication(state, stage) is not None):
                raise ObservationError('Only one sonication can be performed on the separate Input')
            if state['recipe']['pending_observation'] is not None:
                raise TaskError('Reconcile the pending physical recipe observation before sonication')
            if not self._phase_assessment(state, stage, sources.LYSIS)['conformant']:
                raise TaskError('Extraction addition, mixing and qualified lysis evidence must precede sonication')
            material = self._reaction(state, reaction_id)['current_material_id']
            if stage['phase_subjects'][sources.LYSIS]['material_id'] != material:
                raise ObservationError('Only the current lysed input may be sonicated')
            if ledger.remaining(state, material)['value'] is None:
                raise TaskError('Actual lysate fill must be observed before sonication')
            stage['material_id'] = material
            stage['vessel_id'] = state['inventory']['materials'][material]['vessel_id']
        return super()._begin_sonication(state, actor_id, intent_id, reaction_id, stage_run_id, output_material_id, reason)

    def _confirm_sonication(self, state, actor_id, intent_id, actual_output_quantity, observed_vessel_id, reason):
        meta = self._sonication(state, intent_id)
        if not self._resolving_sonication and state['bookings'][intent_id]['outcome'] != 'performed':
            if state['recovery_required'] or meta['intent_session'] != state['session']:
                raise TaskError('An interrupted sonication needs explicit resolve_sonication')
        return super()._confirm_sonication(state, actor_id, intent_id, actual_output_quantity, observed_vessel_id, reason)

    def _resolve_sonication(self, state, actor_id, intent_id, outcome, reason,
                            actual_output_quantity=None, observed_vessel_id=None):
        self._resolving_sonication = True
        try:
            return super()._resolve_sonication(state, actor_id, intent_id, outcome, reason,
                                              actual_output_quantity, observed_vessel_id)
        finally:
            self._resolving_sonication = False

    def _resolve_action(self, state, actor_id, intent_id, **kwargs):
        if intent_id in self._intents(state):
            raise TaskError('Reconcile this effect through resolve_sonication')
        return super()._resolve_action(state, actor_id, intent_id, **kwargs)

    def _begin_material_action(self, state, actor_id, **kwargs):
        if kwargs.get('stage_id') == 'S09' and kwargs.get('kind') == 'withdrawal':
            inputs = kwargs.get('inputs')
            stage = self._require_stage(state, 'S09', kwargs['reaction_id'])
            sonic = self._performed_sonication(state, stage)
            if (sonic is None or not isinstance(inputs, list) or len(inputs) != 1
                    or not isinstance(inputs[0], dict) or inputs[0].get('material_id') != sonic['material_after_id']
                    or inputs[0].get('consume_all') is not False or state['recipe']['pending_observation'] is not None
                    or self._input_effect(state, stage, CLARIFICATION, 'separate') is not None):
                raise ObservationError('Size QC needs a separate withdrawal from the sonicated Input before clarification')
            amount = ledger.quantity(inputs[0].get('quantity'))
            if amount['unit'] != 'uL' or amount['value'] is None or amount['value'] <= 0:
                raise TaskError('A separate positive size-QC withdrawal in uL is required')
            return InputSonicationWorkflow._begin_material_action(self, state, actor_id, **kwargs)
        return super()._begin_material_action(state, actor_id, **kwargs)

    def _record_sonication_size(self, state, actor_id, intent_id, size_id, withdrawal_intent_id,
                                minimum_bp, maximum_bp, reason):
        sonic = self._sonication(state, intent_id)
        checksum = state['observation_context']['artifact_sha256']
        receipt = sonic['physical_receipt']
        if receipt is not None and checksum == receipt['observation']['artifact_sha256']:
            raise TaskError('Fragment-size evidence needs its own original result')
        return super()._record_sonication_size(state, actor_id, intent_id, size_id, withdrawal_intent_id,
                                             minimum_bp, maximum_bp, reason)

    def _complete_stage(self, state, actor_id, stage_run_id, receipts, action_ids, reason):
        stage = self._stage(state, stage_run_id)
        if stage['stage_id'] == 'S09':
            sonic = self._performed_sonication(state, stage)
            if sonic is None or not sonic['size_records']:
                raise TaskError('S09 completion requires identified fragment-size evidence and its confirmed QC withdrawal')
        return super()._complete_stage(state, actor_id, stage_run_id, receipts, action_ids, reason)

    def _report(self, state, trace):
        report = super()._report(state, trace)
        definition = state['definition']
        fixture = definition['test_fixture_only']
        mode = definition['runtime_profile']['mode']
        report.update(mode=mode, test_fixture_only=fixture, preparation_complete=definition['preparation_complete'],
                      runtime_engine=self.ENGINE)
        report['sonication'].update(mode=mode, test_fixture_only=fixture)
        for intent in report['sonication']['intents'].values():
            for record in intent['size_records'].values():
                record['local_size_criteria_conformant'] = record.pop('fixture_range_conformant')
        return report
