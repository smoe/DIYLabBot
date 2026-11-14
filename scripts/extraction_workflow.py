"""Shared ordered synthetic extraction observations on the common material journal.

This engine never commands a centrifuge, pipette or TapeStation. Fixture phase
observations, ledger effects, original QC bytes and their review share one Root.
"""
import copy
import importlib
import math
from pathlib import Path
import uuid

import material_ledger as ledger
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, ManualWorkflow, ObservationError, keys, text
from material_workflow import MaterialWorkflow


def require(condition, message):
    if not condition:
        raise TaskError(message)


def number(value, label, *, minimum=None):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite ' + label + ' required')
    if minimum is not None:
        require(value >= minimum, label + ' is below its minimum')
    return value


class ExtractionWorkflow(MaterialWorkflow):
    STATE_FORMAT = 'solidcraftbot.material-workflow-state/2'
    REPORT_FORMAT = None
    ENGINE = None
    SOURCE_MODULE = None
    RUN_PREFIX = None
    EFFECT_PREFIX = None
    RECOVERY_PREFIX = None
    WORK_AREA = 'SYN.Extraction.WorkArea'
    LIMITATIONS = ()
    STEPS = ('accept_inventory', 'confirm_inventory', 'workspace_clear', 'claim',
             'begin_phase', 'confirm_phase', 'advance_time', 'mark_effect_unknown', 'resolve_effect',
             'confirm_tapestation_ready', 'begin_qc_preparation', 'confirm_qc_preparation',
             'begin_tapestation', 'confirm_tapestation_loaded', 'confirm_tapestation_run_complete',
             'confirm_tapestation_abort',
             'import_results', 'review_tapestation', 'discard_tapestation_import',
             'set_disposition', 'resolve_quantity', 'release')
    RECOVERY_COMMANDS = {'reconcile', 'cancel', 'check_deadline', 'mark_effect_unknown',
                         'resolve_effect', 'advance_time', 'set_disposition',
                         'confirm_inventory', 'resolve_quantity', 'finish_cancel', 'confirm_tapestation_abort'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    @classmethod
    def create(cls, journal, source=None, run_id=None):
        require(cls.ENGINE and cls.SOURCE_MODULE and cls.RUN_PREFIX,
                'An explicit source-bound extraction engine is required')
        definition = importlib.import_module(cls.SOURCE_MODULE).load(source)
        identity = run_id or cls.RUN_PREFIX + uuid.uuid4().hex[:12]
        retention = {} if any('retention_after' in step for step in definition['execution']['steps']) else None
        process = {'engine': cls.ENGINE, 'cursor': 0, 'phase_pending': None,
                   'operations': {}, 'deviations': [], 'aborted_phase': None,
                   'qc': {'readiness': None, 'preparations': {}, 'request': None,
                          'loaded': None, 'run_complete': None, 'review': None, 'abort': None}}
        if retention is not None:
            process['retention'] = retention
        return cls._create_definition(journal, definition, run_id=identity, extra_state={
            'protective_operations': {},
            'process': process})

    @classmethod
    def _validate_format(cls, state):
        super()._validate_format(state)
        definition = state.get('definition', {})
        require(definition.get('format') == 'solidcraftbot.material-workflow-definition/2'
                and cls.ENGINE is not None and definition.get('profile', {}).get('type') == cls.ENGINE
                and state.get('process', {}).get('engine') == cls.ENGINE,
                'Explicit synthetic extraction /2 composition required; no journal migration')

    @staticmethod
    def _verify_sources(state):
        for name, expected in state['definition']['source_files_sha256'].items():
            path = (ROOT / name).resolve()
            try:
                matches = path.is_relative_to(ROOT) and path.is_file() and digest(path.read_bytes()) == expected
            except OSError:
                matches = False
            require(matches, 'extraction source changed; inspect the pinned run before migration: ' + name)

    def _before_transition(self, state):
        self._verify_sources(state)

    @classmethod
    def _clock_matches(cls, journal, state, clock_mode=None):
        require(state['definition'].get('clock_mode') == 'synthetic_events/1'
                and clock_mode in (None, 'synthetic_events/1'), 'extraction synthetic event clock required')

    @classmethod
    def _resources(cls, state):
        result = set(MaterialWorkflow._resources(state))
        qc = state['definition']['execution']['qc']
        result.add('instrument:' + qc['instrument_id'])
        result.add('work-area:' + state['definition']['execution'].get('work_area_id', cls.WORK_AREA))
        for vessel in state['inventory']['vessels'].values():
            if vessel['location']['kind'] == 'rack':
                result.add('rack:' + vessel['location']['rack_id'])
        return sorted(result)

    def _pending(self, state):
        return state['process']['phase_pending'] or state['pending_operation']

    def _after_transition(self, state, command, actor_id, data, *, rejected=False):
        if rejected:
            state['process']['deviations'].append({'command': command, 'actor_id': actor_id,
                'arguments': copy.deepcopy(data), 'recorded_at_s': state['logical_time_s'],
                'evidence': 'synthetic_input', 'requires_abort': True})
        if state['status'] not in {'completed', 'cancelled'}:
            state['resources'] = self._resources(state)

    def _normal(self, state):
        self._claimed(state)
        require(state['status'] == 'working' and not state['recovery_required'],
                'Reconciled working extraction task required')
        require(not state['process']['deviations'] and not state['process']['aborted_phase'],
                'Observed deviation or nonperformed phase requires controlled abort')
        require(self._pending(state) is None, 'Resolve the current process intent first')

    @staticmethod
    def _execution(state):
        return state['definition']['execution']

    def _sample(self, state, sample_id):
        samples = self._execution(state)['samples']
        require(sample_id in samples, 'Unknown extraction sample identity')
        require(len(samples) == 1, 'This extraction engine supports one sample per Root')
        return samples[sample_id]

    def _step(self, state, phase_id):
        found = [step for step in self._execution(state)['steps'] if step['id'] == phase_id]
        require(len(found) == 1, 'Unknown extraction phase')
        return found[0]

    @staticmethod
    def _effect(spec):
        inputs, outputs = spec.get('inputs', []), spec.get('outputs', [])
        return None if not inputs and not outputs else {'kind': 'transformation' if outputs else 'withdrawal',
            'inputs': copy.deepcopy(inputs), 'outputs': copy.deepcopy(outputs)}

    def _begin(self, state, actor_id, intent_id, identity, spec):
        text(intent_id, 'process intent identity')
        signature = {'identity': identity, 'effect': self._effect(spec),
                     'parameters': copy.deepcopy(spec.get('parameters', {})),
                     'required_checks': copy.deepcopy(spec.get('required_checks', []))}
        for field in ['retention_after', 'output_units', 'parameter_scopes', 'required_positive_outputs']:
            if field in spec:
                signature[field] = copy.deepcopy(spec[field])
        previous = state['process']['operations'].get(intent_id)
        if previous is not None:
            require(previous['request'] == signature, 'Conflicting extraction process intent')
            return False
        self._normal(state)
        operation = {'intent_id': intent_id, 'request': signature, 'state': 'intent',
                     'started_at_s': state['logical_time_s'], 'confirmation': None}
        effect = signature['effect']
        if effect is not None:
            ledger.begin_effect(state, actor_id, intent_id, effect['kind'], effect['inputs'], effect['outputs'],
                                self.EFFECT_PREFIX + '.' + identity['kind'] + '.' + identity['id'])
            state['inventory_confirmation'] = None
        state['process']['operations'][intent_id] = operation
        state['process']['phase_pending'] = {'intent_id': intent_id}

    def _begin_phase(self, state, actor_id, sample_id, phase_id, intent_id):
        self._sample(state, sample_id)
        step = self._step(state, phase_id)
        identity = {'kind': 'phase', 'id': phase_id, 'sample_id': sample_id}
        if intent_id not in state['process']['operations']:
            cursor = state['process']['cursor']
            require(cursor < len(self._execution(state)['steps'])
                    and self._execution(state)['steps'][cursor]['id'] == phase_id,
                    'extraction phase order is fixed by its pinned source')
        return self._begin(state, actor_id, intent_id, identity, step)

    def _operation(self, state, intent_id):
        operation = state['process']['operations'].get(intent_id)
        require(operation is not None, 'Unknown extraction process intent')
        return operation

    def _retention_after(self, state, intent_id, *, abnormal=False):
        """Record named retained fractions, never a second quantity projection."""
        operation = self._operation(state, intent_id)
        declaration = operation['request'].get('retention_after')
        if declaration is None:
            if abnormal:
                sample_id = operation['request']['identity']['sample_id']
                previous = state['process'].get('retention', {}).get(sample_id)
                if previous is not None:
                    state['process']['retention'][sample_id] = {
                        'intent_id': intent_id, 'planned': copy.deepcopy(previous['planned']),
                        'confirmed': False, 'evidence': 'synthetic_input',
                        'previous_retention_intent_id': previous['intent_id']}
            return
        keys(declaration, 'material_id vessel_id pellet supernatant retained state', 'retained fraction declaration')
        for key in ['material_id', 'vessel_id', 'retained', 'state']:
            text(declaration[key], 'retained fraction ' + key)
        for key in ['pellet', 'supernatant']:
            require(declaration[key] is None or isinstance(declaration[key], str) and declaration[key].strip(),
                    'Named fraction or explicit absence required')
        require(declaration['retained'] in {'pellet', 'supernatant', 'whole', 'solution', 'composite', 'all'},
                'Unsupported named retained fraction')
        sample_id = operation['request']['identity']['sample_id']
        receipt = {'intent_id': intent_id, 'planned': copy.deepcopy(declaration),
                   'confirmed': not abnormal, 'evidence': 'synthetic_input'}
        if not abnormal:
            material = state['inventory']['materials'].get(declaration['material_id'])
            require(material is not None and material['vessel_id'] == declaration['vessel_id']
                    and material['disposition'] not in {'discarded', 'consumed', 'quarantined'},
                    'Retained fraction must be the live canonical material in its declared physical vessel')
            if material['initial_quantity']['value'] == 0:
                receipt['confirmed'] = False
                state['process']['deviations'].append({'command': 'retention_after', 'intent_id': intent_id,
                    'reason': 'A zero observed continuing fraction does not establish retained DNA', 'requires_abort': True})
                state['recovery_required'], state['workspace_clear'] = self.RECOVERY_PREFIX + '_retention_deviation', False
        state['process'].setdefault('retention', {})[sample_id] = receipt

    @staticmethod
    def _phase_observations(state, operation, observations, *, abnormal=False):
        require(isinstance(observations, dict), 'Explicit phase observations required')
        request = operation['request']; parameters = request['parameters']
        expected = set(request['required_checks'])
        if 'duration_s' in parameters or 'duration_max_s' in parameters: expected.add('duration_s')
        if 'temperature_min_deg_c' in parameters or 'temperature_max_deg_c' in parameters:
            expected.add('temperature_deg_c')
        if 'rcf_min_x_g' in parameters or 'rcf_max_x_g' in parameters: expected.add('rcf_x_g')
        if 'inversion_count' in parameters: expected.add('inversion_count')
        require(set(observations) == expected, 'Exact checks and process measurements required for this phase')
        deviations = []
        for check in request['required_checks']:
            require(type(observations[check]) is bool, 'Boolean phase observation required: ' + check)
            if observations[check] is not True:
                deviations.append('Extraction phase check not positively observed: ' + check)
        if 'duration_s' in observations:
            elapsed = number(observations['duration_s'], 'observed duration', minimum=0)
            actual_elapsed = state['logical_time_s'] - operation['started_at_s']
            if elapsed < parameters.get('duration_s', 0):
                deviations.append('Observed extraction process duration is below its protocol minimum')
            if actual_elapsed + 1e-9 < elapsed:
                if abnormal:
                    deviations.append('Reported duration is not covered by the synthetic process clock')
                else:
                    raise TaskError('Advance the explicit synthetic process clock before confirming elapsed time')
            if 'duration_max_s' in parameters and max(elapsed, actual_elapsed) > parameters['duration_max_s'] + 1e-9:
                deviations.append('Extraction phase exceeded its explicitly source-bound maximum duration')
        if 'temperature_deg_c' in observations:
            actual = number(observations['temperature_deg_c'], 'observed temperature')
            if not parameters.get('temperature_min_deg_c', -math.inf) <= actual <= parameters.get('temperature_max_deg_c', math.inf):
                deviations.append('Observed extraction temperature is outside its source-bound interval')
        if 'rcf_x_g' in observations:
            actual = number(observations['rcf_x_g'], 'observed relative centrifugal force', minimum=0)
            if actual < parameters.get('rcf_min_x_g', 0):
                deviations.append('Observed relative centrifugal force is below the protocol minimum')
            if actual > parameters.get('rcf_max_x_g', math.inf):
                deviations.append('Observed relative centrifugal force is above the protocol maximum')
        if 'inversion_count' in parameters:
            actual = observations['inversion_count']
            number(actual, 'observed inversion count', minimum=0)
            require(actual == int(actual), 'Integer inversion count required')
            if actual != parameters['inversion_count']:
                deviations.append('Observed inversion count differs from the source-bound procedure')
        if deviations and not abnormal:
            raise ObservationError(deviations[0])
        return deviations

    def _confirm(self, state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason,
                 *, resolving=False, abnormal=False):
        operation = self._operation(state, intent_id)
        confirmation = {'actual_inputs': copy.deepcopy(actual_inputs), 'actual_outputs': copy.deepcopy(actual_outputs),
                        'observations': copy.deepcopy(observations), 'reason': text(reason, 'process confirmation reason')}
        if abnormal:
            confirmation['performed_abnormal'] = True
        if operation['state'] == 'performed':
            require(operation['confirmation'] == confirmation, 'Conflicting repeated extraction confirmation')
            return False
        self._claimed(state)
        require(state['process']['phase_pending'] == {'intent_id': intent_id}
                and operation['state'] in {'intent', 'unknown'}, 'This is not the open process intent')
        if not resolving:
            require(state['status'] == 'working' and not state['recovery_required'], 'Reconcile before confirming an old intent')
        if operation['request']['identity']['kind'] == 'qc_preparation':
            observation_deviations = self._qc_preparation_observations(state, operation, observations, abnormal=abnormal)
        else:
            observation_deviations = self._phase_observations(state, operation, observations, abnormal=abnormal)
        effect = operation['request']['effect']
        output_units = operation['request'].get('output_units')
        if output_units is not None:
            require(isinstance(actual_outputs, list), 'Explicit typed output observations required')
            for output in actual_outputs:
                require(isinstance(output, dict) and output.get('material_id') in output_units,
                        'Output identity is not declared by the extraction source')
                quantity = ledger.validate_quantity(output.get('quantity'), zero=True)
                require(quantity['unit'] == output_units[output['material_id']],
                        'Observed output unit differs from its source-bound fraction type')
        if effect is None:
            require(actual_inputs == [] and actual_outputs == [], 'A process-only phase must not invent material effects')
        else:
            ledger.confirm_effect(state, actor_id, intent_id, actual_inputs, actual_outputs, reason)
            state['inventory_confirmation'] = None
        operation = self._operation(state, intent_id)
        operation.update(state='performed', confirmation=confirmation, confirmed_at_s=state['logical_time_s'])
        state['process']['phase_pending'] = None
        identity = operation['request']['identity']
        if identity['kind'] == 'phase':
            cursor = state['process']['cursor']
            require(self._execution(state)['steps'][cursor]['id'] == identity['id'], 'Corrupt extraction phase cursor')
            state['process']['cursor'] += 1
        else:
            state['process']['qc']['preparations'][identity['id']] = intent_id
        if abnormal:
            quarantine = {output['material_id'] for output in effect['outputs']} if effect is not None else set()
            retention = operation['request'].get('retention_after')
            if retention is None:
                previous = state['process'].get('retention', {}).get(identity['sample_id'])
                retention = None if previous is None else previous['planned']
            if retention is not None:
                quarantine.add(retention['material_id'])
            for material_id in quarantine:
                material = state['inventory']['materials'][material_id]
                if material['vessel_id'] is not None and material['disposition'] not in {'consumed', 'discarded'}:
                    ledger.set_disposition(state, actor_id, material_id, 'quarantined', reason)
            state['process']['deviations'].append({'command': 'performed_abnormal', 'intent_id': intent_id,
                'observation_deviations': observation_deviations, 'reason': reason, 'requires_abort': True,
                'evidence': 'synthetic_input'})
            state['recovery_required'], state['workspace_clear'] = self.RECOVERY_PREFIX + '_abnormal_performed', False
            self._retention_after(state, intent_id, abnormal=True)
        else:
            self._retention_after(state, intent_id)
        deviations = []
        observed_outputs = {item['material_id']: item['quantity'] for item in actual_outputs}
        for material_id in operation['request'].get('required_positive_outputs', []):
            require(material_id in observed_outputs, 'Required prepared output has no typed quantity observation')
            quantity = observed_outputs[material_id]
            if quantity['value'] == 0:
                deviations.append({'material_id': material_id, 'required': 'not_known_empty',
                                   'observed': copy.deepcopy(quantity)})
        if effect is not None:
            actual = {item['material_id']: item['quantity'] for item in actual_inputs}
            for planned in effect['inputs']:
                wanted, observed = planned['quantity'], actual[planned['material_id']]
                if wanted['value'] is not None and (observed['value'] is None
                        or observed['unit'] != wanted['unit']
                        or not math.isclose(observed['value'], wanted['value'], rel_tol=0, abs_tol=1e-9)):
                    deviations.append({'material_id': planned['material_id'], 'planned': copy.deepcopy(wanted),
                                       'observed': copy.deepcopy(observed)})
        if identity['kind'] == 'qc_preparation':
            required_volume = sum(item['quantity']['value'] for item in effect['inputs'])
            for output in actual_outputs:
                value = output['quantity']
                if (value['unit'] != 'uL' or value['value'] is None
                        or not math.isclose(value['value'], required_volume, rel_tol=0, abs_tol=1e-9)):
                    deviations.append({'material_id': output['material_id'],
                        'planned': {'value': required_volume, 'unit': 'uL'}, 'observed': copy.deepcopy(value)})
        if deviations:
            state['process']['deviations'].append({'command': 'confirm_process_effect',
                'intent_id': intent_id, 'actual_quantity_deviations': deviations,
                'requires_abort': True, 'evidence': 'synthetic_input'})
            state['recovery_required'], state['workspace_clear'] = self.RECOVERY_PREFIX + '_protocol_quantity_deviation', False

    def _confirm_phase(self, state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason):
        require(self._operation(state, intent_id)['request']['identity']['kind'] == 'phase', 'Extraction phase intent required')
        return self._confirm(state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason)

    def _mark_effect_unknown(self, state, actor_id, intent_id, reason):
        self._claimed(state)
        operation = self._operation(state, intent_id)
        require(state['process']['phase_pending'] == {'intent_id': intent_id}
                and operation['state'] in {'intent', 'unknown'}, 'Open extraction intent required')
        text(reason, 'unknown process effect reason')
        if operation['request']['effect'] is not None:
            ledger.mark_unknown(state, actor_id, intent_id, reason)
        operation = self._operation(state, intent_id)
        operation.update(state='unknown', uncertainty={'actor_id': actor_id, 'reason': reason, 'evidence': 'synthetic_input'})
        state['recovery_required'], state['workspace_clear'] = self.RECOVERY_PREFIX + '_effect_unknown', False

    def _resolve_effect(self, state, actor_id, intent_id, outcome, actual_inputs=None, actual_outputs=None,
                        observations=None, reason=None):
        require(state['recovery_required'] or state['status'] == 'cancelling', 'Explicit process recovery required')
        operation = self._operation(state, intent_id)
        require(state['process']['phase_pending'] == {'intent_id': intent_id}, 'Current unresolved intent required')
        if outcome == 'performed':
            self._confirm(state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason, resolving=True)
        elif outcome == 'performed_abnormal':
            self._confirm(state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason,
                          resolving=True, abnormal=True)
        elif outcome == 'unknown':
            require(actual_inputs in (None, []) and actual_outputs in (None, []) and observations in (None, {}),
                    'Unknown effect cannot supply invented actuals')
            return self._mark_effect_unknown(state, actor_id, intent_id, reason)
        elif outcome == 'not_performed':
            require(actual_inputs in (None, []) and actual_outputs in (None, []) and observations in (None, {}),
                    'Nonperformance cannot supply actual quantities')
            text(reason, 'nonperformance evidence reason')
            if operation['request']['effect'] is not None:
                ledger.not_performed(state, actor_id, intent_id, reason)
            operation = self._operation(state, intent_id)
            operation.update(state='not_performed', nonperformance={'actor_id': actor_id, 'reason': reason})
            state['process']['phase_pending'] = None
            state['process']['aborted_phase'] = intent_id
        else:
            raise TaskError('Explicit performed, performed_abnormal, not_performed or unknown outcome required')
        state['recovery_required'], state['workspace_clear'] = self.RECOVERY_PREFIX + '_inventory_reconciliation_required', False

    def _reconcile(self, state, actor_id, observations, workspace_clear, reason=None):
        require(state['process']['phase_pending'] is None and state['pending_operation'] is None,
                'Resolve the explicit extraction process effect before confirming its inventory')
        return super()._reconcile(state, actor_id, observations, workspace_clear)

    def _advance_time(self, state, actor_id, seconds):
        number(seconds, 'synthetic elapsed seconds', minimum=0)
        require(seconds > 0, 'Positive synthetic elapsed seconds required')
        state['logical_time_s'] += seconds

    def _extraction_complete(self, state):
        require(state['process']['cursor'] == len(self._execution(state)['steps']), 'Complete extraction extraction before TapeStation preparation')

    def _confirm_tapestation_ready(self, state, actor_id, observations, reason):
        self._normal(state); self._extraction_complete(state)
        qc = self._execution(state)['qc']
        require(isinstance(observations, dict)
                and set(observations) == set(qc['required_checks']) | {'buffer_equilibration_s'},
                'Exact synthetic TapeStation readiness observations required')
        for check in qc['required_checks']:
            if observations[check] is not True: raise ObservationError('TapeStation readiness missing: ' + check)
        actual = number(observations['buffer_equilibration_s'], 'buffer equilibration time', minimum=0)
        if actual < qc['parameters']['buffer_equilibration_s']:
            raise ObservationError('TapeStation buffer equilibration is incomplete')
        receipt = {'observations': copy.deepcopy(observations), 'reason': text(reason, 'readiness reason')}
        previous = state['process']['qc']['readiness']
        if previous is not None:
            require(previous == receipt, 'Conflicting TapeStation readiness confirmation')
            return False
        state['process']['qc']['readiness'] = receipt

    def _begin_qc_preparation(self, state, actor_id, role, intent_id):
        require(role in {'ladder', 'sample'}, 'Explicit sample or ladder preparation role required')
        qc = self._execution(state)['qc']; process = state['process']['qc']
        if intent_id not in state['process']['operations']:
            self._normal(state); self._extraction_complete(state)
            require(process['readiness'] is not None and role not in process['preparations']
                    and process['request'] is None, 'Fresh manual TapeStation preparation required')
        spec = {**copy.deepcopy(qc[role]['effect']), 'parameters': copy.deepcopy(qc['parameters']),
                'required_checks': []}
        return self._begin(state, actor_id, intent_id,
                           {'kind': 'qc_preparation', 'id': role,
                            'sample_id': next(iter(self._execution(state)['samples']))}, spec)

    @staticmethod
    def _qc_preparation_observations(state, operation, observations, *, abnormal=False):
        fields = {'capped', 'mixed', 'spun_down', 'mix_duration_s', 'mix_rpm', 'spin_duration_s'}
        require(isinstance(observations, dict) and set(observations) == fields, 'Exact TapeStation preparation observations required')
        deviations = []
        for check in ['capped', 'mixed', 'spun_down']:
            require(type(observations[check]) is bool, 'Boolean TapeStation preparation observation required: ' + check)
            if observations[check] is not True: deviations.append('TapeStation preparation not confirmed: ' + check)
        parameters = operation['request']['parameters']
        mix = number(observations['mix_duration_s'], 'observed TapeStation mixing duration', minimum=0)
        spin = number(observations['spin_duration_s'], 'observed TapeStation spin duration', minimum=0)
        rpm = number(observations['mix_rpm'], 'observed TapeStation mixing speed', minimum=0)
        if mix < parameters['mix_duration_s'] or spin < parameters['spin_duration_s'] or rpm != parameters['mix_rpm']:
            deviations.append('TapeStation preparation differs from the pinned synthetic procedure')
        if state['logical_time_s'] - operation['started_at_s'] + 1e-9 < mix + spin:
            if abnormal:
                deviations.append('TapeStation preparation duration is not covered by the synthetic clock')
            else:
                raise TaskError('Advance the synthetic preparation clock before confirming sequential mixing and spin')
        if deviations and not abnormal:
            raise ObservationError(deviations[0])
        return deviations

    def _confirm_qc_preparation(self, state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason):
        require(self._operation(state, intent_id)['request']['identity']['kind'] == 'qc_preparation',
                'TapeStation preparation intent required')
        return self._confirm(state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason)

    @staticmethod
    def _qc_output(qc, role):
        outputs = qc[role]['effect']['outputs']
        require(len(outputs) == 1, 'One identified TapeStation preparation output required')
        return outputs[0]

    @staticmethod
    def _product_vessel(sample):
        vessel_id = sample.get('product_vessel_id', sample.get('elution_vessel_id'))
        return text(vessel_id, 'product vessel identity')

    def _begin_tapestation(self, state, actor_id, instrument_run_id, analysis_id, measurement_id,
                           screen_tape_id, lane_id, ladder_lane_id):
        self._normal(state); self._extraction_complete(state)
        process = state['process']['qc']; qc = self._execution(state)['qc']
        for value in [instrument_run_id, analysis_id, measurement_id, screen_tape_id]: text(value, 'TapeStation run identity')
        require(set(process['preparations']) == {'sample', 'ladder'} and process['request'] is None,
                'Both separately confirmed TapeStation preparations are required')
        require(lane_id == qc['sample']['lane_id'] and ladder_lane_id == qc['ladder']['lane_id']
                and lane_id != ladder_lane_id, 'Pinned distinct sample and ladder lanes required')
        sample_id, sample = next(iter(self._execution(state)['samples'].items()))
        aliquot, ladder = self._qc_output(qc, 'sample'), self._qc_output(qc, 'ladder')
        for item in [aliquot, ladder]:
            material = state['inventory']['materials'].get(item['material_id'])
            require(material is not None and material['vessel_id'] == item['vessel_id']
                    and material['disposition'] not in {'discarded', 'consumed', 'quarantined'},
                    'Identified prepared TapeStation sample and ladder must remain present')
        product = state['inventory']['materials'][sample['product_material_id']]
        product_vessel = self._product_vessel(sample)
        require(product['vessel_id'] == product_vessel
                and product['disposition'] not in {'consumed', 'discarded', 'quarantined'}, 'Retained eluate must remain identified')
        expected = {'workflow_run_id': self.run_id, 'instrument_run_id': instrument_run_id,
            'analysis_id': analysis_id, 'instrument_id': qc['instrument_id'],
            'assay_id': qc['assay_id'], 'assay_revision': qc['assay_revision'], 'measurements': [{
                'measurement_id': measurement_id, 'lane_id': lane_id, 'sample_id': sample_id,
                'product_material_id': sample['product_material_id'], 'product_vessel_id': product_vessel,
                'product_content_revision': state['inventory']['vessels'][product_vessel]['content_revision'],
                'aliquot_material_id': aliquot['material_id'], 'aliquot_vessel_id': aliquot['vessel_id'],
                'aliquot_content_revision': state['inventory']['vessels'][aliquot['vessel_id']]['content_revision']}]}
        process['request'] = {'expected': expected, 'screen_tape_id': screen_tape_id,
            'ladder_lane_id': ladder_lane_id, 'ladder_material_id': ladder['material_id'],
            'ladder_vessel_id': ladder['vessel_id'],
            'ladder_content_revision': state['inventory']['vessels'][ladder['vessel_id']]['content_revision']}

    def expected_tapestation(self):
        request = self.state['process']['qc']['request']
        require(request is not None, 'No TapeStation run has been explicitly requested')
        return copy.deepcopy(request['expected'])

    @staticmethod
    def _loading(request):
        sample = request['expected']['measurements'][0]
        return {'sample_material_id': sample['aliquot_material_id'], 'sample_vessel_id': sample['aliquot_vessel_id'],
            'ladder_material_id': request['ladder_material_id'], 'ladder_vessel_id': request['ladder_vessel_id'],
            'sample_lane_id': sample['lane_id'], 'ladder_lane_id': request['ladder_lane_id'],
            'screen_tape_id': request['screen_tape_id']}

    def expected_tapestation_loading(self):
        request = self.state['process']['qc']['request']
        require(request is not None, 'No TapeStation loading request exists')
        return self._loading(request)

    def _live_tapestation(self, state):
        qc = state['process']['qc']; request = qc['request']
        require(request is not None, 'Explicit TapeStation request required')
        row = request['expected']['measurements'][0]
        expected = [(row['product_material_id'], row['product_vessel_id'], row['product_content_revision']),
                    (row['aliquot_material_id'], row['aliquot_vessel_id'], row['aliquot_content_revision']),
                    (request['ladder_material_id'], request['ladder_vessel_id'], request['ladder_content_revision'])]
        for material_id, vessel_id, revision in expected:
            material = state['inventory']['materials'][material_id]
            vessel = state['inventory']['vessels'][vessel_id]
            if (material['vessel_id'] != vessel_id
                    or material['disposition'] in {'discarded', 'consumed', 'quarantined'}
                    or vessel['content_revision'] != revision):
                raise ObservationError('Prepared TapeStation or source material identity/content revision changed')
        for role in ['sample', 'ladder']:
            material_id = self._qc_output(self._execution(state)['qc'], role)['material_id']
            balance = ledger.remaining(state, material_id)
            if balance['value'] is None or balance['value'] <= 0:
                raise ObservationError('TapeStation requires a positive identified preparation')

    def _confirm_tapestation_loaded(self, state, actor_id, observations, reason):
        self._normal(state)
        qc = state['process']['qc']; request = qc['request']
        require(request is not None, 'Explicit TapeStation request required')
        self._live_tapestation(state)
        expected = {**self._loading(request), 'sample_loaded': True, 'ladder_loaded': True, 'identities_confirmed': True}
        if observations != expected:
            raise ObservationError('Observed TapeStation loading identities or confirmations differ')
        receipt = {'observations': copy.deepcopy(observations), 'reason': text(reason, 'TapeStation loading reason')}
        if qc['loaded'] is not None:
            require(qc['loaded'] == receipt, 'Conflicting TapeStation loading confirmation')
            return False
        qc['loaded'] = receipt

    def _confirm_tapestation_run_complete(self, state, actor_id, observations, reason):
        self._normal(state)
        qc = state['process']['qc']; request = qc['request']
        require(request is not None and qc['loaded'] is not None, 'Confirmed manual TapeStation loading required')
        self._live_tapestation(state)
        expected = {'run_complete': True, 'ladder_accepted': True,
            'instrument_run_id': request['expected']['instrument_run_id'], 'analysis_id': request['expected']['analysis_id']}
        if observations != expected:
            raise ObservationError('TapeStation run completion and ladder acceptance are explicit observations')
        receipt = {'observations': copy.deepcopy(observations), 'reason': text(reason, 'TapeStation run completion reason')}
        if qc['run_complete'] is not None:
            require(qc['run_complete'] == receipt, 'Conflicting TapeStation completion')
            return False
        qc['run_complete'] = receipt

    @classmethod
    def _abort_identities(cls, request):
        return {**cls._loading(request), 'instrument_run_id': request['expected']['instrument_run_id'],
                'analysis_id': request['expected']['analysis_id']}

    def expected_tapestation_abort(self):
        request = self.state['process']['qc']['request']
        require(request is not None, 'No TapeStation request exists to reconcile')
        return self._abort_identities(request)

    def _confirm_tapestation_abort(self, state, actor_id, observations, reason):
        self._claimed(state)
        qc = state['process']['qc']; request = qc['request']
        require(state['status'] == 'cancelling' and request is not None,
                'Controlled cancellation of an identified TapeStation request required')
        expected = {**self._abort_identities(request), 'instrument_stopped': True,
                    'sample_retrieved': True, 'ladder_retrieved': True,
                    'materials_accounted': True, 'identities_confirmed': True}
        if observations != expected:
            raise ObservationError('Explicit stopped, retrieved and accounted TapeStation identities required')
        receipt = {'observations': copy.deepcopy(observations), 'actor_id': actor_id,
                   'reason': text(reason, 'TapeStation abort reconciliation reason'), 'evidence': 'synthetic_input'}
        if qc['abort'] is not None:
            require(qc['abort'] == receipt, 'Conflicting TapeStation abort receipt')
            return False
        qc['abort'] = receipt

    def import_file(self, path, actor_id, origin='synthetic_export'):
        from tapestation_results import MAX_REPORT_BYTES
        path = Path(path)
        with path.open('rb') as stream:
            content = stream.read(MAX_REPORT_BYTES + 1)
        require(len(content) <= MAX_REPORT_BYTES, 'TapeStation report exceeds the bounded import size')
        return self.act('import_results', actor_id, artifact=content, file_name=path.name, origin=origin)

    def _import_results(self, state, artifact, file_name, origin='synthetic_export'):
        import tapestation_results as decoder
        self._normal(state)
        require(origin == 'synthetic_export', 'Only explicitly synthetic TapeStation reports are supported')
        require(isinstance(artifact, bytes) and len(artifact) <= decoder.MAX_REPORT_BYTES,
                'Bounded original TapeStation report bytes required')
        text(file_name, 'TapeStation report file name')
        process = state['process']['qc']; request = process['request']
        require(request is not None and process['run_complete'] is not None,
                'Manual TapeStation run completion required before result import')
        self._live_tapestation(state)
        checksum = digest(artifact)
        if checksum in state['imports']: return False
        try:
            parsed = decoder.parse_report(artifact, request['expected'], protocol=self._execution(state)['qc']['protocol'])
            issues = copy.deepcopy(parsed['issues'])
        except TaskError as error:
            parsed, issues = None, [str(error)]
        if any(item['status'] == 'accepted' for item in state['imports'].values()):
            issues.append('conflicting_tapestation_result_import')
        policy = self._execution(state)['qc'].get('policy')
        assessments = [] if parsed is None else [decoder.evaluate(row, policy=policy,
            protocol=self._execution(state)['qc']['protocol']) for row in parsed['rows']]
        state['imports'][checksum] = {'file_name': Path(file_name).name, 'sha256': checksum, 'byte_count': len(artifact),
            'origin': origin, 'status': 'quarantined' if issues else 'accepted', 'issues': issues,
            'report': parsed, 'assessments': assessments, 'disposition': None, 'disposition_reason': None}
        process['review'] = None

    def _discard_tapestation_import(self, state, actor_id, sha256, reason):
        self._normal(state)
        item = state['imports'].get(sha256)
        require(item is not None and item['status'] == 'quarantined', 'Known quarantined TapeStation import required')
        receipt = text(reason, 'quarantined report disposition reason')
        if item['disposition'] == 'discarded':
            require(item['disposition_reason'] == receipt, 'Conflicting report disposition')
            return False
        item.update(disposition='discarded', disposition_reason=receipt)

    def _review_tapestation(self, state, actor_id, decision, artifact_sha256, reason):
        self._normal(state)
        self._live_tapestation(state)
        require(decision in {'accept', 'reject'}, 'Explicit TapeStation QC review decision required')
        item = state['imports'].get(artifact_sha256)
        require(item is not None and item['status'] == 'accepted' and item['report'] is not None,
                'A matching, nonquarantined original TapeStation report is required')
        if decision == 'accept':
            require(item['assessments'] and all(value['synthetic_policy_passed'] for value in item['assessments']),
                    'TapeStation results do not satisfy the explicitly synthetic review policy')
        review = {'decision': decision, 'artifact_sha256': artifact_sha256, 'actor_id': actor_id,
                  'reason': text(reason, 'TapeStation review reason'), 'evidence': 'synthetic_input'}
        previous = state['process']['qc']['review']
        if previous is not None:
            require(previous == review, 'Conflicting TapeStation review')
            return False
        state['process']['qc']['review'] = review
        item.update(disposition='reviewed', disposition_reason=reason)
        if decision == 'reject':
            state['process']['deviations'].append({'command': 'review_tapestation', 'requires_abort': True,
                                                  'reason': reason, 'artifact_sha256': artifact_sha256})

    def act(self, command, actor_id, artifact=None, **data):
        require(command in set(self.STEPS) | {'reconcile', 'cancel', 'finish_cancel', 'check_deadline'},
                'Only explicit extraction commands are supported; generic/legacy operations cannot bypass the process')
        return ManualWorkflow.act(self, command, actor_id, artifact=artifact, **data)

    def _set_disposition(self, state, actor_id, material_id, disposition, reason):
        if state['status'] != 'cancelling' and disposition in {'discarded', 'consumed', 'quarantined'}:
            qc = state['process']['qc']
            protected = {sample['product_material_id'] for sample in self._execution(state)['samples'].values()}
            protected.update(self._qc_output(self._execution(state)['qc'], role)['material_id'] for role in ['sample', 'ladder'])
            require(material_id not in protected or qc['review'] is not None,
                    'Keep the eluate, sample and ladder identified until explicit TapeStation review or controlled abort')
        return super()._set_disposition(state, actor_id, material_id, disposition, reason)

    def _audit_process(self, state):
        self._validate_format(state); ledger.audit(state)
        steps = self._execution(state)['steps']; completed = set()
        for intent_id, operation in state['process']['operations'].items():
            require(intent_id == operation['intent_id'], 'Corrupt process intent identity')
            effect = operation['request']['effect']
            if effect is not None:
                booking = state['bookings'].get(intent_id)
                require(booking is not None and booking['outcome'] == operation['state'], 'Process and ledger outcomes differ')
                require(booking['request']['inputs'] == effect['inputs'] and booking['request']['outputs'] == effect['outputs'],
                        'Process and ledger material identities differ')
            identity = operation['request']['identity']
            if identity['kind'] == 'phase':
                spec = self._step(state, identity['id'])
                for field in ['retention_after', 'output_units', 'parameter_scopes', 'required_positive_outputs']:
                    require(operation['request'].get(field) == spec.get(field),
                            'Process retention/type intent differs from its immutable source')
            if operation['state'] == 'performed' and identity['kind'] == 'phase':
                require(identity['id'] not in completed, 'A extraction phase has multiple performed intents')
                completed.add(identity['id'])
        require(completed == {step['id'] for step in steps[:state['process']['cursor']]}, 'Phase cursor and confirmed ordered effects differ')

    def _restored(self, state):
        self._audit_process(state)
        if state['status'] == 'cancelling' and state['process']['qc']['request'] is not None:
            require(state['process']['qc']['abort'] is not None,
                    'Confirm stopped, retrieved and accounted TapeStation work before releasing cancellation resources')
        super()._restored(state)

    def _release(self, state, actor_id, workspace_clear):
        self._normal(state); self._extraction_complete(state)
        qc = state['process']['qc']; review = qc['review']
        require(qc['run_complete'] and review and review['decision'] == 'accept', 'Explicit accepted TapeStation QC review required')
        require(all(item['disposition'] is not None for item in state['imports'].values()), 'Resolve every preserved TapeStation import before release')
        source_qc = self._execution(state)['qc']
        for role in ['sample', 'ladder']:
            output = self._qc_output(source_qc, role)
            require(state['inventory']['materials'][output['material_id']]['disposition'] == 'discarded',
                    'Explicitly dispose the measured TapeStation sample and ladder preparations')
        for sample in self._execution(state)['samples'].values():
            require(state['inventory']['materials'][sample['product_material_id']]['disposition'] == 'retained',
                    'Retain the identified DNA eluate product')
        return super()._release(state, actor_id, workspace_clear)

    def _report(self, state, trace):
        self._audit_process(state)
        result = super()._report(state, trace)
        result.update(format=self.REPORT_FORMAT, process=copy.deepcopy(state['process']),
                      imports=copy.deepcopy(state['imports']), synthetic_extraction_sequence_executed=state['process']['cursor'] == len(self._execution(state)['steps']),
                      tapestation_network_executed=False, tapestation_hardware_executed=False,
                      fragment_size_qualified=False, sop_qualified=False)
        result['limitations'] = list(self.LIMITATIONS)
        result['passed'] = bool(state['status'] == 'completed' and not state['process']['deviations']
                                and state['process']['qc']['review'] and state['process']['qc']['review']['decision'] == 'accept')
        return result
