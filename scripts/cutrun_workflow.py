"""Synthetic CUT&RUN process observations on the shared material journal.

No hardware effects or biochemical qualification occur here. Every command is
an explicitly synthetic observation. Unknown effects retain their intents;
protective stops use disjoint issued aliquots in the same canonical ledger.
"""
import copy
import json
import math
import uuid

import material_ledger as ledger
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, ManualWorkflow, ObservationError, keys, positive, text
from material_workflow import MaterialWorkflow


class CutRunWorkflow(MaterialWorkflow):
    STATE_FORMAT = 'solidcraftbot.material-workflow-state/2'
    REPORT_FORMAT = 'solidcraftbot.cutrun-workflow-report/1'
    STEPS = ('accept_inventory', 'confirm_inventory', 'workspace_clear', 'claim',
             'begin_phase', 'confirm_phase', 'confirm_stop_readiness', 'begin_stop', 'confirm_stop', 'confirm_stop_mixing',
             'mark_effect_unknown', 'resolve_effect', 'resolve_time_gap', 'advance_time',
             'observe_temperature', 'begin_qc', 'confirm_qc_withdrawal', 'import_results',
             'review_qc', 'set_disposition', 'resolve_quantity', 'abnormal_termination', 'release')
    PROTECTIVE = {'confirm_stop_readiness', 'begin_stop', 'confirm_stop', 'confirm_stop_mixing', 'observe_temperature',
                  'advance_time', 'resolve_time_gap', 'mark_effect_unknown', 'check_deadline'}
    RECOVERY_COMMANDS = PROTECTIVE | {'reconcile', 'resolve_effect', 'cancel',
                                      'abnormal_termination', 'set_disposition', 'confirm_inventory',
                                      'finish_cancel', 'import_results', 'resolve_quantity'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    def __init__(self, journal, run_id, session):
        super().__init__(journal, run_id, session)
        if session is not None:
            definition = self.state['definition']
            runtime = definition.get('runtime_source_files')
            if not runtime:
                raise TaskError('Pinned CUT&RUN runtime manifest required for a writer')
            for file in runtime:
                path = (ROOT / file).resolve()
                try:
                    matches = path.is_relative_to(ROOT) and digest(path.read_bytes()) == definition['source_files_sha256'].get(file)
                except OSError:
                    matches = False
                if not matches:
                    raise TaskError('Runtime source changed; inspect the pinned run before migration: ' + file)

    @classmethod
    def create(cls, journal, source=None, run_id=None):
        from cutrun_workflow_sources import load
        definition = load(source)
        identity = run_id or 'SYN.CUTRUN.RUN.' + uuid.uuid4().hex[:12]
        branches = {}
        for branch in definition['preparation_plan']['branches']:
            branches[branch['id']] = {
                'reaction_id': identity + '.A01.' + branch['id'], 'cursor': 0,
                'current_material_id': branch['input_material_id'], 'reaction_state': 'inactive',
                'activation': None, 'stop': None, 'phase_pending': None,
                'stop_readiness': None,
                'temperature_intervals': [], 'deviations': [], 'qc': {},
                'abnormal_termination': None}
        return cls._create_definition(journal, definition, run_id=identity, extra_state={
            'protective_operations': {},
            'clock': {'uncertainty_s': 0.0, 'gap_required': False, 'gap_base_uncertainty_s': 0.0,
                      'gap_resolution': None},
            'process': {'engine': 'cutrun_synthetic/1', 'branches': branches, 'operations': {},
                        'qc_imports': {}, 'qc_review': None}})

    @classmethod
    def _validate_format(cls, state):
        super()._validate_format(state)
        definition = state.get('definition', {})
        if (definition.get('format') != 'solidcraftbot.material-workflow-definition/2'
                or definition.get('profile', {}).get('type') != 'cutrun_synthetic/1'
                or state.get('process', {}).get('engine') != 'cutrun_synthetic/1'):
            raise TaskError('Closed CUT&RUN /2 definition and process engine required')

    @classmethod
    def _clock_matches(cls, journal, state, clock_mode=None):
        if (state['definition'].get('clock_mode') != 'synthetic_intervals/1'
                or clock_mode not in (None, 'synthetic_intervals/1')):
            raise TaskError('CUT&RUN requires its explicit synthetic interval clock')

    @staticmethod
    def _prepare_reopen(state):
        clock = state['clock']
        if not clock['gap_required']:
            clock['gap_base_uncertainty_s'] = clock['uncertainty_s']
        clock['gap_required'] = True
        clock['uncertainty_s'] = None
        clock['gap_resolution'] = None
        for branch in state['process']['branches'].values():
            branch['stop_readiness'] = None

    @staticmethod
    def _authorize_actor(state, command, actor_id):
        if command in CutRunWorkflow.PROTECTIVE:
            if actor_id not in state['definition']['execution']['stop_actors']:
                raise TaskError('An explicitly declared synthetic stop observer is required')
        else:
            ManualWorkflow._authorize_actor(state, command, actor_id)

    @staticmethod
    def _time(state):
        lower, width = state['logical_time_s'], state['clock']['uncertainty_s']
        return {'min_s': lower, 'max_s': None if width is None else lower + width}

    @staticmethod
    def _branch(state, branch_id, reaction_id):
        branch = state['process']['branches'].get(branch_id)
        if branch is None or branch['reaction_id'] != reaction_id:
            raise ObservationError('Explicit branch/reaction/attempt identity mismatch')
        plan = next(item for item in state['definition']['preparation_plan']['branches'] if item['id'] == branch_id)
        return branch, plan

    @staticmethod
    def _operation(state, intent_id, reaction_id):
        operation = state['process']['operations'].get(intent_id)
        if operation is None or operation['reaction_id'] != reaction_id:
            raise ObservationError('Explicit process intent/reaction identity mismatch')
        return operation

    @staticmethod
    def _hold(state, branch, code, reason):
        if code not in {item['code'] for item in branch['deviations']}:
            branch['deviations'].append({'code': code, 'reason': reason,
                'observed_at': CutRunWorkflow._time(state), 'evidence': 'synthetic_input'})
        state['recovery_required'] = 'cutrun_quality_deviation'
        state['workspace_clear'] = False

    def _evaluate(self, state):
        now = self._time(state)
        for branch in state['process']['branches'].values():
            if branch['activation'] and branch['reaction_state'] in {'possibly_active', 'active', 'stop_dosed_unmixed'}:
                deadline = branch['activation']['stop_deadline_s']
                if not state['clock']['gap_required'] and (now['max_s'] is None or now['max_s'] > deadline):
                    self._hold(state, branch, 'reaction_deadline_exceeded',
                               'The latest possible process time exceeds the immutable synthetic stop deadline.')

    def _resolve_time_gap(self, state, actor_id, min_s, max_s, reason):
        text(reason, 'elapsed-time evidence')
        positive(min_s, 'minimum elapsed seconds', zero=True)
        if max_s is not None:
            positive(max_s, 'maximum elapsed seconds', zero=True)
            if max_s < min_s:
                raise TaskError('Elapsed-time interval is reversed')
        clock = state['clock']
        if not clock['gap_required']:
            raise TaskError('No unresolved session time gap')
        state['logical_time_s'] += min_s
        base = clock['gap_base_uncertainty_s']
        clock['uncertainty_s'] = None if base is None or max_s is None else base + max_s - min_s
        clock['gap_required'] = False
        clock['gap_resolution'] = {'min_s': min_s, 'max_s': max_s, 'reason': reason,
                                   'actor_id': actor_id, 'evidence': 'synthetic_input'}
        self._evaluate(state)

    def _advance_time(self, state, actor_id, seconds):
        positive(seconds, 'synthetic elapsed seconds')
        state['logical_time_s'] += seconds
        self._evaluate(state)
        if state['deadline_s'] is not None and state['logical_time_s'] >= state['deadline_s']:
            state['recovery_required'] = state['recovery_required'] or 'deadline_exceeded'
            state['workspace_clear'] = False

    def _check_deadline(self, state, actor_id):
        self._evaluate(state)

    def _observe_temperature(self, state, actor_id, branch_id, reaction_id, start_s, end_s, temperature_deg_c):
        branch, unused = self._branch(state, branch_id, reaction_id)
        positive(start_s, 'temperature interval start', zero=True)
        positive(end_s, 'temperature interval end', zero=True)
        if end_s < start_s or end_s > state['logical_time_s']:
            raise TaskError('Temperature coverage must be an observed interval within the known process clock')
        if type(temperature_deg_c) not in (int, float) or not math.isfinite(temperature_deg_c):
            raise TaskError('Finite synthetic temperature required')
        record = {'start_s': start_s, 'end_s': end_s, 'temperature_deg_c': temperature_deg_c,
                  'actor_id': actor_id, 'evidence': 'synthetic_input'}
        if record in branch['temperature_intervals']:
            return False
        branch['temperature_intervals'].append(record)
        # A contradictory interval cannot be repaired by overlaying a good one.
        if branch['activation']:
            target = self._activation_step(unused)['parameters']['temperature_deg_c']['value']
            stopped = branch['stop']['completed_at'] if branch['stop'] else None
            stop_upper = stopped['max_s'] if stopped else None
            if (end_s > branch['activation']['contact']['min_s'] and (stop_upper is None or start_s < stop_upper)
                    and abs(temperature_deg_c - target) > state['definition']['execution']['temperature_tolerance_deg_c']):
                self._hold(state, branch, 'temperature_out_of_range', 'Observed temperature exceeds a synthetic tolerance.')
        for operation in state['process']['operations'].values():
            if operation['branch_id'] != branch_id or operation['status'] == 'not_performed':
                continue
            step = next((item for item in unused['steps'] if item['operation'] == operation['operation']), None)
            if step is None or operation['operation'] in {'activate_digest', 'stop_reaction'}:
                continue
            target = step['parameters'].get('temperature_deg_c', {}).get('value')
            completed = operation.get('completed_at', self._time(state))
            if (target is not None and end_s > operation['started_at']['min_s']
                    and (completed['max_s'] is None or start_s < completed['max_s'])
                    and abs(temperature_deg_c - target) > state['definition']['execution']['temperature_tolerance_deg_c']):
                self._hold(state, branch, 'temperature_out_of_range', 'A late or current interval contradicts a phase temperature requirement.')

    @staticmethod
    def _activation_step(plan):
        return next(item for item in plan['steps'] if item['operation'] == 'activate_digest')

    def _temperature_check(self, state, branch, start, end, target):
        if end is None:
            self._hold(state, branch, 'temperature_coverage_unknown', 'Unbounded time has no complete temperature coverage.')
            return
        tolerance = state['definition']['execution']['temperature_tolerance_deg_c']
        cursor = start
        for item in sorted(branch['temperature_intervals'], key=lambda item: item['start_s']):
            if item['end_s'] <= start or item['start_s'] >= end:
                continue
            if abs(item['temperature_deg_c'] - target) > tolerance:
                self._hold(state, branch, 'temperature_out_of_range', 'Observed interval exceeds a synthetic temperature tolerance.')
            if item['start_s'] <= cursor + 1e-9:
                cursor = max(cursor, item['end_s'])
        if cursor < end - 1e-9:
            self._hold(state, branch, 'temperature_coverage_missing', 'Endpoint readings do not cover the complete process interval.')

    def _normal_work(self, state):
        self._claimed(state)
        if state['status'] != 'working' or state['recovery_required'] or state['clock']['gap_required']:
            raise TaskError('Reconciled working process required')
        if state['clock']['uncertainty_s'] is None:
            raise TaskError('Unbounded process time prevents nominal phase progress')
        if any(branch['deviations'] or branch['abnormal_termination'] for branch in state['process']['branches'].values()):
            raise TaskError('Quality deviations prevent nominal phase progress')
        if any(item['status'] in {'intent', 'unknown'} for item in state['process']['operations'].values()):
            raise TaskError('Resolve the open process effect before ordinary work')

    @staticmethod
    def _inputs(state, material_id):
        balance = ledger.remaining(state, material_id)
        if balance['knowledge'] != 'known':
            raise TaskError('Known material amount required at this synthetic fraction boundary')
        return [{'material_id': material_id, 'quantity': {'value': balance['value'], 'unit': balance['unit']}, 'consume_all': True}]

    def _phase_effect(self, state, branch, plan, operation):
        """Compile semantic fraction transitions, never infer an actual yield."""
        identity = plan['id']
        binding = state['definition']['execution']['branches'][identity]
        current = branch['current_material_id']
        if not self._descends(state, current, plan['input_material_id']):
            raise TaskError('Fraction ancestry must remain inside its own identified branch')
        if operation in {'prepare_cells', 'prepare_input'}:
            outputs = [{'material_id': identity + '.ReactionMaterial', 'kind': 'intermediate',
                        'vessel_id': plan['vessels']['reaction'], 'role': 'identified_reaction_material'}]
        elif operation in {'isolate_product', 'clarify_input'}:
            outputs = [{'material_id': identity + '.Supernatant', 'kind': 'intermediate',
                        'vessel_id': binding['fraction_vessels']['supernatant'], 'role': 'product_containing_supernatant'},
                       {'material_id': identity + '.BeadRemainder', 'kind': 'byproduct',
                        'vessel_id': binding['fraction_vessels']['bead_remainder'],
                        'role': 'retained_bead_remainder' if plan['workflow'] == 'cutrun' else 'retained_input_pellet'}]
        elif operation == 'bind_column':
            outputs = [{'material_id': identity + '.ColumnMaterial', 'kind': 'intermediate',
                        'vessel_id': plan['vessels']['column'], 'role': 'column_bound_analyte'},
                       {'material_id': identity + '.FlowThrough', 'kind': 'byproduct',
                        'vessel_id': plan['vessels']['collection'], 'role': 'retained_flow_through'}]
        elif operation == 'elute':
            outputs = [{'material_id': plan['product_material_id'], 'kind': 'product',
                        'vessel_id': plan['vessels']['product'], 'role': 'purified_dna'},
                       {'material_id': identity + '.ColumnResidue', 'kind': 'byproduct',
                        'vessel_id': binding['fraction_vessels']['column_residue'], 'role': 'retained_column_residue'}]
        elif operation == 'activate_digest':
            dose = self._activation_step(plan)['parameters']['volume_ul']['value']
            return 'withdrawal', [{'material_id': binding['activation_material_id'],
                'quantity': {'value': dose, 'unit': 'uL'}, 'consume_all': False}], []
        else:
            return None, [], []
        return 'transformation', self._inputs(state, current), outputs

    @staticmethod
    def _target_changed(state, operation, *, confirmed=False):
        material = state['inventory']['materials'][operation['target_material_id']]
        material['disposition_confirmation'] = None
        vessel = state['inventory']['vessels'][operation['target_vessel_id']]
        vessel['mass_confirmation_valid'] = False
        if confirmed:
            vessel['content_revision'] += 1

    def _stop_capacity(self, state, candidate, plan):
        now = self._time(state)
        execution = state['definition']['execution']
        if now['max_s'] is None:
            raise TaskError('Unknown latest process time prevents activation')
        jobs = []
        for branch_id, branch in state['process']['branches'].items():
            if branch['activation'] and branch['reaction_state'] != 'stopped':
                contact = branch['activation']['contact']
                readiness = branch['stop_readiness']
                if not readiness or not readiness['access'] or not readiness['mixing_available']:
                    raise TaskError('Existing possible reactions need current stop readiness before another activation')
                if contact['max_s'] is None or branch['stop']:
                    raise TaskError('Uncertain activation or stop prevents another activation')
                duration = self._activation_step(next(item for item in state['definition']['preparation_plan']['branches'] if item['id'] == branch_id))['parameters']['duration_s']['value']
                jobs.append((branch['activation']['stop_deadline_s'], contact['max_s'] + duration))
        duration = self._activation_step(plan)['parameters']['duration_s']['value']
        jobs.append((now['min_s'] + duration + execution['stop_window_s'],
                     now['max_s'] + execution['activation_service_s'] + duration))
        cursor = now['max_s'] + execution['activation_service_s']
        service = execution['stop_service_s']
        for deadline, release in sorted(jobs):
            cursor = max(cursor, release) + service
            if cursor > deadline + 1e-9:
                raise TaskError('Synthetic serial stop service cannot meet every earliest possible deadline')

    def _begin_phase(self, state, actor_id, branch_id, operation, intent_id, reaction_id):
        branch, plan = self._branch(state, branch_id, reaction_id)
        text(intent_id, 'process intent identity')
        old = state['process']['operations'].get(intent_id)
        if old:
            if (old['branch_id'], old['operation'], old['reaction_id']) != (branch_id, operation, reaction_id):
                raise TaskError('Conflicting process intent identity')
            return False
        self._normal_work(state)
        if branch['cursor'] >= len(plan['steps']) or plan['steps'][branch['cursor']]['operation'] != operation:
            raise TaskError('Phase order is fixed by the pinned E1 branch')
        if operation == 'stop_reaction':
            raise TaskError('Use the explicit protective stop command')
        if operation == 'activate_digest':
            if plan['workflow'] != 'cutrun' or branch['reaction_state'] != 'inactive':
                raise TaskError('Only a previously inactive CUT&RUN branch may activate')
            binding = state['definition']['execution']['branches'][branch_id]
            readiness = branch['stop_readiness']
            if not readiness or not readiness['access'] or not readiness['mixing_available']:
                raise TaskError('Current explicit stop access and mixing readiness required before activation')
            dose = state['definition']['preparation_plan']['stop_plan']['dose_per_branch_ul']['value']
            if ledger.remaining(state, binding['stop_material_id'])['value'] is None or ledger.remaining(state, binding['stop_material_id'])['value'] < dose:
                raise TaskError('Issued stop material must be available before activation')
            self._stop_capacity(state, branch, plan)
        kind, inputs, outputs = self._phase_effect(state, branch, plan, operation)
        if kind:
            ledger.begin_effect(state, actor_id, intent_id, kind, inputs, outputs, 'synthetic_cutrun_' + operation)
            self._after_material_change(state, True)
            branch = state['process']['branches'][branch_id]
        started = self._time(state)
        state['process']['operations'][intent_id] = {'branch_id': branch_id, 'reaction_id': reaction_id,
            'operation': operation, 'status': 'intent', 'started_at': started,
            'material_effect': kind is not None, 'confirmation': None,
            'target_material_id': branch['current_material_id'],
            'target_vessel_id': state['inventory']['materials'][branch['current_material_id']]['vessel_id']}
        branch['phase_pending'] = intent_id
        if operation == 'activate_digest':
            self._target_changed(state, state['process']['operations'][intent_id])
            duration = self._activation_step(plan)['parameters']['duration_s']['value']
            branch['activation'] = {'intent_id': intent_id, 'contact': {'min_s': started['min_s'], 'max_s': None},
                'stop_deadline_s': started['min_s'] + duration + state['definition']['execution']['stop_window_s'],
                'dose_confirmed': False, 'mixing_confirmed': False}
            branch['reaction_state'] = 'possibly_active'

    def _phase_receipt(self, state, actor_id, operation, observations, reason):
        text(reason, 'phase observation reason')
        if not isinstance(observations, dict):
            raise TaskError('Explicit phase observations required')
        return {'observations': copy.deepcopy(observations), 'reason': reason,
                'actor_id': actor_id, 'evidence': 'synthetic_input'}

    def _confirm_phase(self, state, actor_id, intent_id, reaction_id, observations, reason):
        operation = self._operation(state, intent_id, reaction_id)
        if operation['operation'].startswith('qc:') or operation['operation'] == 'stop_reaction':
            raise TaskError('Use the matching QC/stop receipt command')
        receipt = self._phase_receipt(state, actor_id, operation, observations, reason)
        if operation['confirmation'] is not None:
            if operation['confirmation'] != receipt:
                raise TaskError('Conflicting phase receipt')
            return False
        if operation['status'] not in {'intent', 'unknown'}:
            raise TaskError('The phase intent is already resolved without performance')
        branch, plan = self._branch(state, operation['branch_id'], reaction_id)
        phase = operation['operation']
        if branch['phase_pending'] != intent_id:
            raise TaskError('Phase is not the unresolved branch intent')
        step = plan['steps'][branch['cursor']]
        if step['operation'] != phase:
            raise TaskError('Frozen phase cursor mismatch')
        now, started = self._time(state), operation['started_at']
        if phase == 'activate_digest':
            keys(observations, 'dose_ul mixed', 'activation receipt')
            if observations['dose_ul'] is not None:
                positive(observations['dose_ul'], 'observed activation dose')
            if type(observations['mixed']) is not bool:
                raise TaskError('Explicit activation mixing observation required')
            if started['max_s'] is None or now['min_s'] < started['max_s'] + state['definition']['execution']['activation_service_s']:
                raise ObservationError('Observe the synthetic activation service interval before its receipt')
            binding = state['definition']['execution']['branches'][plan['id']]
            ledger.confirm_effect(state, actor_id, intent_id,
                [{'material_id': binding['activation_material_id'], 'quantity': {'value': observations['dose_ul'], 'unit': 'uL'}}], [], reason)
            operation = state['process']['operations'][intent_id]
            branch = state['process']['branches'][operation['branch_id']]
            self._target_changed(state, operation, confirmed=True)
            activation = branch['activation']
            activation['dose_confirmed'], activation['mixing_confirmed'] = observations['dose_ul'] is not None, observations['mixed']
            activation['contact']['max_s'] = now['max_s']
            if branch['stop'] and branch['stop']['completed_at'] is not None:
                branch['reaction_state'] = 'stopped'
            else:
                branch['reaction_state'] = 'active' if observations['mixed'] else 'possibly_active'
            expected = step['parameters']['volume_ul']['value']
            if observations['dose_ul'] != expected:
                self._hold(state, branch, 'activation_dose_deviation', 'Observed activation dose differs from the synthetic planned dose.')
            if not observations['mixed']:
                self._hold(state, branch, 'activation_mixing_unconfirmed', 'Possible contact remains active without a mixing receipt.')
        else:
            duration = step['parameters'].get('duration_s', {}).get('value', 0)
            if started['max_s'] is None or now['min_s'] < started['max_s'] + duration - 1e-9:
                raise ObservationError('The required phase duration has not been observed')
            if duration and (now['max_s'] is None or now['max_s'] > started['min_s'] + duration + state['definition']['execution']['phase_tolerance_s']):
                self._hold(state, branch, 'phase_time_deviation:' + phase, 'Phase time exceeds an explicitly synthetic tolerance.')
            if observations.get('completed') is not True:
                raise ObservationError('Explicit completion observation required; a timer alone is insufficient')
            if phase == 'isolate_product' and observations.get('cleared') is not True:
                raise ObservationError('Observed cleared suspension required before product separation')
            if phase == 'check_input_size':
                size = positive(observations.get('fragment_size_bp'), 'observed input fragment size')
                if size >= 10000:
                    raise ObservationError('Input size is incompatible with the pinned column constraint')
            if operation['material_effect']:
                booking = state['bookings'][intent_id]
                actual = observations.get('outputs')
                if not isinstance(actual, list):
                    raise TaskError('Explicit observed output quantities required; yields are not inferred')
                ledger.confirm_effect(state, actor_id, intent_id,
                    [{'material_id': item['material_id'], 'quantity': copy.deepcopy(item['quantity'])}
                     for item in booking['request']['inputs']], actual, reason)
                operation = state['process']['operations'][intent_id]
                branch = state['process']['branches'][operation['branch_id']]
                branch['current_material_id'] = booking['request']['outputs'][0]['material_id']
            temperature = step['parameters'].get('temperature_deg_c', {}).get('value')
            if temperature is not None and duration:
                self._temperature_check(state, branch, started['min_s'], now['max_s'], temperature)
        operation['confirmation'], operation['status'], operation['completed_at'] = receipt, 'performed', now
        branch['phase_pending'] = None
        branch['cursor'] += 1
        if phase == 'activate_digest' and branch['reaction_state'] == 'stopped':
            branch['cursor'] += 1  # The separately observed protective stop already completed.
        self._after_material_change(state, True)
        self._evaluate(state)

    def _confirm_stop_readiness(self, state, actor_id, branch_id, reaction_id, access, mixing_available):
        branch, plan = self._branch(state, branch_id, reaction_id)
        if plan['workflow'] != 'cutrun' or type(access) is not bool or type(mixing_available) is not bool:
            raise TaskError('Explicit access/mixing readiness for a CUT&RUN branch required')
        branch['stop_readiness'] = {'access': access, 'mixing_available': mixing_available,
                                    'actor_id': actor_id, 'observed_at': self._time(state),
                                    'evidence': 'synthetic_input'}
        if branch['activation'] and branch['reaction_state'] in {'possibly_active', 'active', 'stop_dosed_unmixed'} and (not access or not mixing_available):
            self._hold(state, branch, 'stop_readiness_lost', 'Observed loss of access or mixing readiness while contact remains possible.')

    def _begin_stop(self, state, actor_id, branch_id, reaction_id, intent_id, access, mixing_available):
        self._claimed(state)
        branch, plan = self._branch(state, branch_id, reaction_id)
        if plan['workflow'] != 'cutrun' or not branch['activation']:
            raise TaskError('Only a possibly activated CUT&RUN branch has a chemical stop path')
        if type(access) is not bool or type(mixing_available) is not bool:
            raise TaskError('Explicit stop access and mixing readiness required')
        old = state['process']['operations'].get(intent_id)
        if old:
            if (old['branch_id'], old['operation'], old['reaction_id']) != (branch_id, 'stop_reaction', reaction_id):
                raise TaskError('Conflicting stop intent identity')
            return False
        if branch['stop']:
            raise TaskError('Resolve the existing stop; do not dose again')
        binding = state['definition']['execution']['branches'][branch_id]
        dose = state['definition']['preparation_plan']['stop_plan']['dose_per_branch_ul']['value']
        available = ledger.remaining(state, binding['stop_material_id'])
        if not access or not mixing_available or available['value'] is None or available['value'] < dose:
            self._hold(state, branch, 'stop_path_blocked', 'Observed stop access, mixing readiness or issued material is insufficient.')
            return
        ledger.begin_protective_stop(state, actor_id, intent_id, plan['vessels']['reaction'],
                                     binding['stop_material_id'], {'value': dose, 'unit': 'uL'})
        branch = state['process']['branches'][branch_id]
        started = self._time(state)
        state['process']['operations'][intent_id] = {'branch_id': branch_id, 'reaction_id': reaction_id,
            'operation': 'stop_reaction', 'status': 'intent', 'started_at': started,
            'material_effect': True, 'confirmation': None,
            'target_material_id': branch['current_material_id'], 'target_vessel_id': plan['vessels']['reaction']}
        self._target_changed(state, state['process']['operations'][intent_id])
        branch['stop'] = {'intent_id': intent_id, 'dose_confirmed': False, 'mixing_confirmed': False,
                          'completed_at': None, 'mixing_receipt': None}
        self._after_material_change(state, True)

    def _finish_stop_observation(self, state, branch, plan, actor_id):
        now = self._time(state)
        branch['reaction_state'] = 'stopped'
        branch['stop']['completed_at'] = now
        activation = branch['activation']
        duration = self._activation_step(plan)['parameters']['duration_s']['value']
        if now['max_s'] is None or now['max_s'] > activation['stop_deadline_s']:
            self._hold(state, branch, 'late_stop', 'A real synthetic stop receipt was preserved after the earliest possible deadline.')
        contact_upper = activation['contact']['max_s']
        if contact_upper is None or now['min_s'] < contact_upper + duration:
            self._hold(state, branch, 'early_or_uncertain_stop', 'Protective stopping is recorded without claiming a nominal digestion interval.')
        self._temperature_check(state, branch, activation['contact']['min_s'], now['max_s'],
                                self._activation_step(plan)['parameters']['temperature_deg_c']['value'])
        # An unresolved activation remains pending; no imaginary receipt is made.
        if branch['phase_pending'] is None and plan['steps'][branch['cursor']]['operation'] == 'stop_reaction':
            branch['cursor'] += 1

    def _confirm_stop(self, state, actor_id, intent_id, reaction_id, actual_volume_ul, mixed, reason):
        operation = self._operation(state, intent_id, reaction_id)
        if operation['operation'] != 'stop_reaction':
            raise TaskError('The receipt is not bound to a stop intent')
        if actual_volume_ul is not None:
            positive(actual_volume_ul, 'observed stop dose')
        if type(mixed) is not bool:
            raise TaskError('Explicit stop mixing observation required')
        receipt = {'actual_volume_ul': actual_volume_ul, 'mixed': mixed, 'reason': text(reason, 'stop evidence'),
                   'actor_id': actor_id, 'evidence': 'synthetic_input'}
        if operation['confirmation'] is not None:
            if operation['confirmation'] != receipt:
                raise TaskError('Conflicting stop receipt; use mixing-only confirmation after an unmixed dose')
            return False
        branch, plan = self._branch(state, operation['branch_id'], reaction_id)
        binding = state['definition']['execution']['branches'][plan['id']]
        ledger.confirm_protective_stop(state, actor_id, intent_id,
            [{'material_id': binding['stop_material_id'], 'quantity': {'value': actual_volume_ul, 'unit': 'uL'}}], reason)
        operation = state['process']['operations'][intent_id]
        branch = state['process']['branches'][operation['branch_id']]
        self._target_changed(state, operation, confirmed=True)
        operation['confirmation'], operation['status'], operation['completed_at'] = receipt, 'performed', self._time(state)
        stop = branch['stop']
        stop['dose_confirmed'], stop['mixing_confirmed'] = actual_volume_ul is not None, mixed
        expected = state['definition']['preparation_plan']['stop_plan']['dose_per_branch_ul']['value']
        start_upper = operation['started_at']['max_s']
        if start_upper is None or state['logical_time_s'] < start_upper + state['definition']['execution']['stop_service_s']:
            self._hold(state, branch, 'short_stop_service', 'The stop receipt is preserved with less than the synthetic service interval.')
        if actual_volume_ul != expected:
            self._hold(state, branch, 'stop_dose_deviation', 'Observed dose differs from the synthetic stopping requirement.')
        if mixed and actual_volume_ul is not None and actual_volume_ul >= expected:
            self._finish_stop_observation(state, branch, plan, actor_id)
        else:
            branch['reaction_state'] = 'stop_dosed_unmixed'
            self._hold(state, branch, 'stop_mixing_or_dose_unconfirmed', 'A dose alone does not establish stopping.')
        self._after_material_change(state, True)

    def _confirm_stop_mixing(self, state, actor_id, intent_id, reaction_id, mixed, reason):
        operation = self._operation(state, intent_id, reaction_id)
        branch, plan = self._branch(state, operation['branch_id'], reaction_id)
        stop = branch['stop']
        if not stop or stop['intent_id'] != intent_id or not stop['dose_confirmed']:
            raise TaskError('An already confirmed stop dose is required for mixing-only evidence')
        receipt = {'mixed': mixed, 'reason': text(reason, 'mixing evidence'), 'actor_id': actor_id}
        if stop['mixing_receipt'] is not None:
            if stop['mixing_receipt'] != receipt:
                raise TaskError('Conflicting stop mixing receipt')
            return False
        if stop['completed_at'] is not None or stop['mixing_confirmed']:
            raise TaskError('The first confirmed stop instant is immutable; no additional mixing receipt is pending')
        if mixed is not True:
            raise ObservationError('Stopping still lacks a mixing observation')
        expected = state['definition']['preparation_plan']['stop_plan']['dose_per_branch_ul']['value']
        if operation['confirmation']['actual_volume_ul'] < expected:
            raise TaskError('Mixing cannot repair an insufficient confirmed dose')
        stop['mixing_confirmed'], stop['mixing_receipt'] = True, receipt
        self._finish_stop_observation(state, branch, plan, actor_id)

    def _mark_effect_unknown(self, state, actor_id, intent_id, reason):
        operation = state['process']['operations'].get(intent_id)
        if operation is None or operation['status'] not in {'intent', 'unknown'}:
            raise TaskError('An unresolved process effect is required')
        if actor_id != state['actor_id'] and operation['operation'] != 'stop_reaction':
            raise TaskError('A stop observer cannot resolve another actor\'s ordinary effects')
        if operation['material_effect']:
            if operation['operation'] == 'stop_reaction':
                ledger.mark_protective_unknown(state, actor_id, intent_id, reason)
            else:
                ledger.mark_unknown(state, actor_id, intent_id, reason)
            operation = state['process']['operations'][intent_id]
        operation['status'] = 'unknown'
        operation['uncertainty_reason'] = text(reason, 'uncertain effect reason')
        state['recovery_required'], state['workspace_clear'] = 'unknown_process_effect', False

    def _resolve_effect(self, state, actor_id, intent_id, reaction_id, outcome, observations, reason):
        operation = self._operation(state, intent_id, reaction_id)
        if outcome == 'unknown':
            return self._mark_effect_unknown(state, actor_id, intent_id, reason)
        if outcome == 'performed':
            if operation['operation'] == 'stop_reaction':
                keys(observations, 'actual_volume_ul mixed', 'resolved stop receipt')
                return self._confirm_stop(state, actor_id, intent_id, reaction_id, reason=reason, **observations)
            if operation['operation'].startswith('qc:'):
                keys(observations, 'actual_volume_ul', 'resolved QC withdrawal')
                return self._confirm_qc_withdrawal(state, actor_id, intent_id, reaction_id, reason=reason, **observations)
            return self._confirm_phase(state, actor_id, intent_id, reaction_id, observations, reason)
        if outcome != 'not_performed':
            raise TaskError('Explicit performed, not_performed or unknown outcome required')
        text(reason, 'effect reconciliation evidence')
        if operation['status'] == 'not_performed':
            if operation.get('nonperformance_reason') != reason:
                raise TaskError('Conflicting nonperformance receipt')
            return False
        if operation['status'] not in {'intent', 'unknown'}:
            raise TaskError('A confirmed effect cannot be declared absent')
        branch, plan = self._branch(state, operation['branch_id'], reaction_id)
        if operation['material_effect']:
            if operation['operation'] == 'stop_reaction':
                ledger.resolve_protective_stop(state, actor_id, intent_id, 'not_performed', [], reason)
            else:
                ledger.not_performed(state, actor_id, intent_id, reason)
            operation = state['process']['operations'][intent_id]
            branch = state['process']['branches'][operation['branch_id']]
        operation['status'], operation['nonperformance_reason'] = 'not_performed', reason
        if branch['phase_pending'] == intent_id:
            branch['phase_pending'] = None
        if operation['operation'] == 'activate_digest':
            if branch['stop']:
                self._hold(state, branch, 'activation_absent_after_protective_stop', 'A protective dose prevents a nominal replay of the original branch.')
            else:
                branch['activation'], branch['reaction_state'] = None, 'inactive'
        elif operation['operation'] == 'stop_reaction':
            self._hold(state, branch, 'stop_confirmed_absent', 'Stopping is not established; this issued stop intent will not be silently recycled.')
        self._after_material_change(state, True)

    def _reconcile(self, state, actor_id, observations, workspace_clear, reason):
        if not state['recovery_required']:
            raise TaskError('No reconciliation is pending')
        text(reason, 'reconciliation evidence')
        if type(workspace_clear) is not bool:
            raise TaskError('Explicit workspace observation required')
        self._confirm_inventory(state, actor_id, observations)
        unresolved = any(item['status'] in {'intent', 'unknown'} for item in state['process']['operations'].values())
        quality = any(branch['deviations'] for branch in state['process']['branches'].values())
        quarantined_qc = any(not item['accepted'] for item in state['process']['qc_imports'].values())
        state['workspace_clear'] = workspace_clear
        state['recovery_required'] = ('unknown_process_effect' if unresolved else
                                      'unresolved_time_gap' if state['clock']['gap_required'] else
                                      'cutrun_quality_deviation' if quality else
                                      'quarantined_qc_artifact' if quarantined_qc else
                                      'deadline_exceeded' if state['deadline_s'] is not None and state['logical_time_s'] >= state['deadline_s'] else None)
        # In particular, neither task nor chemical deadlines are renewed here.
        self._evaluate(state)

    def _begin_qc(self, state, actor_id, branch_id, reaction_id, intent_id, method):
        branch, plan = self._branch(state, branch_id, reaction_id)
        old = state['process']['operations'].get(intent_id)
        if old:
            if (old['branch_id'], old['operation'], old['reaction_id']) != (branch_id, 'qc:' + method, reaction_id):
                raise TaskError('Conflicting QC intent identity')
            return False
        self._normal_work(state)
        if branch['cursor'] != len(plan['steps']) or branch['current_material_id'] != plan['product_material_id']:
            raise TaskError('QC withdraws only from the completed identified purified DNA product')
        qc = state['definition']['preparation_plan']['qc']
        if method not in qc['methods'] or method in branch['qc']:
            raise TaskError('One identified withdrawal per required product QC method')
        volume = qc['aliquot_volumes_ul'][method]['value']
        ledger.begin_effect(state, actor_id, intent_id, 'withdrawal',
            [{'material_id': plan['product_material_id'], 'quantity': {'value': volume, 'unit': 'uL'}, 'consume_all': False}],
            [], 'synthetic_product_qc:' + method)
        state['process']['operations'][intent_id] = {'branch_id': branch_id, 'reaction_id': reaction_id,
            'operation': 'qc:' + method, 'status': 'intent', 'started_at': self._time(state),
            'material_effect': True, 'confirmation': None}
        self._after_material_change(state, True)

    def _confirm_qc_withdrawal(self, state, actor_id, intent_id, reaction_id, actual_volume_ul, reason):
        operation = self._operation(state, intent_id, reaction_id)
        if not operation['operation'].startswith('qc:'):
            raise TaskError('QC withdrawal receipt requires a QC intent')
        if actual_volume_ul is not None:
            positive(actual_volume_ul, 'observed product QC withdrawal')
        receipt = {'actual_volume_ul': actual_volume_ul, 'reason': text(reason, 'QC withdrawal evidence'), 'actor_id': actor_id}
        if operation['confirmation'] is not None:
            if operation['confirmation'] != receipt:
                raise TaskError('Conflicting QC withdrawal receipt')
            return False
        branch, plan = self._branch(state, operation['branch_id'], reaction_id)
        ledger.confirm_effect(state, actor_id, intent_id,
            [{'material_id': plan['product_material_id'], 'quantity': {'value': actual_volume_ul, 'unit': 'uL'}}], [], reason)
        operation = state['process']['operations'][intent_id]
        branch = state['process']['branches'][operation['branch_id']]
        operation['status'], operation['confirmation'] = 'performed', receipt
        branch['qc'][operation['operation'][3:]] = {'withdrawal_intent_id': intent_id, 'artifact_sha256': None}
        if actual_volume_ul is None:
            self._hold(state, branch, 'qc_withdrawal_unknown', 'Performed QC withdrawal has unknown actual consumption, not zero.')
        self._after_material_change(state, True)

    def _import_results(self, state, artifact, file_name, origin='synthetic_export'):
        self._claimed(state)
        text(file_name, 'QC artifact file name')
        if not isinstance(artifact, bytes) or not artifact or origin != 'synthetic_export':
            raise TaskError('Original nonempty synthetic QC artifact bytes required')
        checksum = digest(artifact)
        if checksum in state['process']['qc_imports']:
            return False
        error, result = None, None
        try:
            result = json.loads(artifact)
            keys(result, 'run_id attempt_id reaction_id branch_id material_id method stage value unit below_detection_limit', 'QC record')
            if result['run_id'] != state['run_id'] or result['attempt_id'] != state['attempt_id']:
                raise TaskError('QC run/attempt identity mismatch')
            if type(result['below_detection_limit']) is not bool:
                raise TaskError('Explicit detection-limit status required')
            value = result['value']
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise TaskError('Finite nonnegative QC value or explicit null required')
            if not result['below_detection_limit'] and (value is None or value <= 0):
                raise TaskError('A quantifiable QC value must be positive')
            qc = state['definition']['preparation_plan']['qc']
            ntc = qc['ntc']
            if result['branch_id'] == ntc['id']:
                if (result['reaction_id'] != state['attempt_id'] + '.NTC' or result['material_id'] is not None
                        or result['stage'] != 'pcr_no_template_control' or result['method'] != 'qpcr'
                        or result['unit'] != 'Cq'):
                    raise TaskError('PCR NTC identity, stage or method mismatch')
                if any(item.get('accepted') and item.get('record', {}).get('branch_id') == ntc['id'] for item in state['process']['qc_imports'].values()):
                    raise TaskError('A conflicting NTC record already exists')
            else:
                branch, plan = self._branch(state, result['branch_id'], result['reaction_id'])
                method = result['method']
                if (result['stage'] != 'purified_dna' or result['material_id'] != plan['product_material_id']
                        or method not in qc['methods'] or method not in branch['qc']
                        or result['unit'] != {'fluorometry': 'ng/uL', 'qpcr': 'Cq'}[method]):
                    raise TaskError('Product QC identity, fraction, stage, method or withdrawal mismatch')
                if branch['qc'][method]['artifact_sha256'] is not None:
                    raise TaskError('A conflicting product QC record already exists')
                branch['qc'][method]['artifact_sha256'] = checksum
        except (TaskError, ValueError, TypeError, KeyError, UnicodeDecodeError) as failure:
            error = str(failure)
            try:
                encoded(result)
            except (TypeError, ValueError):
                result = None  # Invalid original bytes are still stored verbatim.
        state['process']['qc_imports'][checksum] = {'file_name': file_name, 'byte_count': len(artifact),
            'record': result, 'accepted': error is None, 'error': error, 'origin': origin,
            'quantifiable': error is None and result['below_detection_limit'] is False}
        state['process']['qc_review'] = None
        if error is not None:
            state['recovery_required'], state['workspace_clear'] = 'quarantined_qc_artifact', False

    def _review_qc(self, state, actor_id, reason):
        text(reason, 'synthetic QC review reason')
        records = state['process']['qc_imports']
        if any(not item['accepted'] for item in records.values()):
            raise TaskError('Quarantined original QC artifacts prevent nominal completion')
        for branch in state['process']['branches'].values():
            for method in state['definition']['preparation_plan']['qc']['methods']:
                record = branch['qc'].get(method)
                if not record or record['artifact_sha256'] is None or not records[record['artifact_sha256']]['quantifiable']:
                    raise TaskError('Complete quantifiable product QC evidence required; below detection is not zero or success')
        ntc_id = state['definition']['preparation_plan']['qc']['ntc']['id']
        ntcs = [item['record'] for item in records.values() if item['record']['branch_id'] == ntc_id]
        if len(ntcs) != 1 or not ntcs[0]['below_detection_limit']:
            raise TaskError('Separate synthetic PCR NTC evidence with no detected signal required')
        state['process']['qc_review'] = {'actor_id': actor_id, 'reason': reason,
            'evidence': 'synthetic_input', 'technical_review_only': True, 'biological_success': None}

    def _abnormal_termination(self, state, actor_id, branch_id, reaction_id, reason):
        branch, plan = self._branch(state, branch_id, reaction_id)
        text(reason, 'abnormal termination and quarantine reason')
        if state['status'] != 'cancelling':
            raise TaskError('Explicit cancellation required before abnormal reaction termination')
        branch['abnormal_termination'] = {'actor_id': actor_id, 'reason': reason,
            'evidence': 'synthetic_input', 'chemical_stop_confirmed': branch['reaction_state'] == 'stopped'}
        if branch['reaction_state'] != 'stopped':
            branch['reaction_state'] = 'abnormally_terminated_unconfirmed_stop'

    @staticmethod
    def _descends(state, material_id, parent_id):
        todo, seen = [material_id], set()
        while todo:
            identity = todo.pop()
            if identity == parent_id:
                return True
            if identity not in seen:
                seen.add(identity)
                todo.extend(state['inventory']['materials'][identity]['parents'])
        return False

    def _set_disposition(self, state, actor_id, material_id, disposition, reason):
        for branch_id, branch in state['process']['branches'].items():
            plan = next(item for item in state['definition']['preparation_plan']['branches'] if item['id'] == branch_id)
            if material_id in state['inventory']['materials'] and self._descends(state, material_id, plan['input_material_id']):
                if branch['abnormal_termination']:
                    if disposition != 'quarantined':
                        raise TaskError('Abnormally terminated material requires explicit quarantine, not disposal or nominal retention')
                elif branch['reaction_state'] not in {'inactive', 'stopped'} or branch['cursor'] != len(plan['steps']):
                    if not (state['status'] == 'cancelling' and branch['reaction_state'] == 'inactive' and disposition == 'retained'):
                        raise TaskError('Complete process or explicit abnormal termination before final disposition')
                elif disposition not in {'retained', 'quarantined'}:
                    raise TaskError('Synthetic process does not imply product/byproduct disposal')
        return super()._set_disposition(state, actor_id, material_id, disposition, reason)

    def _restored(self, state):
        for branch_id, branch in state['process']['branches'].items():
            if branch['activation'] and branch['reaction_state'] != 'stopped' and not branch['abnormal_termination']:
                raise TaskError('Observed dose plus mixing or explicit abnormal termination required before handback')
            if branch['phase_pending'] or any(item['status'] in {'intent', 'unknown'} for item in state['process']['operations'].values()):
                raise TaskError('Every process effect must be explicitly reconciled before handback')
        super()._restored(state)

    def _release(self, state, actor_id, workspace_clear):
        self._normal_work(state)
        if any(branch['cursor'] != len(plan['steps']) for plan in state['definition']['preparation_plan']['branches']
               for branch in [state['process']['branches'][plan['id']]]):
            raise TaskError('Every pinned branch phase must be completed')
        if not state['process']['qc_review']:
            raise TaskError('Explicit synthetic technical QC review required')
        return super()._release(state, actor_id, workspace_clear)

    def act(self, command, actor_id, artifact=None, **data):
        if command == 'import_qc':
            command = 'import_results'
        allowed = set(self.STEPS) | {'reconcile', 'cancel', 'finish_cancel', 'check_deadline'}
        if command not in allowed:
            raise TaskError('Generic material/sample commands cannot bypass CUT&RUN process gates')
        # Use the shared dispatcher, including CAS, artifact transaction and session
        # checks. MaterialWorkflow's legacy import prohibition does not apply.
        return ManualWorkflow.act(self, command, actor_id, artifact=artifact, **data)

    def _report(self, state, trace):
        report = super()._report(state, trace)
        process = copy.deepcopy(state['process'])
        for branch in process['branches'].values():
            activation = branch['activation']
            if activation:
                end = branch['stop']['completed_at'] if branch['stop'] and branch['stop']['completed_at'] else self._time(state)
                contact = activation['contact']
                branch['possible_exposure_s'] = {
                    'min_s': 0 if contact['max_s'] is None else max(0, end['min_s'] - contact['max_s']),
                    'max_s': None if end['max_s'] is None else max(0, end['max_s'] - contact['min_s'])}
            else:
                branch['possible_exposure_s'] = None
        report.update(attempt_id=state['attempt_id'], process=process,
                      clock={**copy.deepcopy(state['clock']), 'now': self._time(state)},
                      protective_operations=copy.deepcopy(state['protective_operations']),
                      synthetic_process_executed=any(item['status'] == 'performed' for item in state['process']['operations'].values()),
                      execution_ready=False, biological_success=None,
                      real_sop_bound=False, real_dosing_qualified=False,
                      synthetic_assumptions=copy.deepcopy(state['definition']['execution']['assumptions']),
                      limitations=[
                          'Synthetic phase, material and QC observations; no real SOP execution or biological success assessment.',
                          'Only activation/stop aliquots, fraction transitions and product QC have material effects; other phase volumes are not reagent recipes.',
                          'All timing, temperature tolerances and demonstration outputs are synthetic assumptions.',
                          'No hardware, watchdog, network, real dispensing, enzyme inactivity or safety qualification.'])
        return report
