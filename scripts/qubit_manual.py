"""Synthetic Qubit-4 preparation, calibration and measurement adapter."""
import copy
import inspect
import math
import uuid

from manual_tasks import TaskError, digest
from manual_workflow import (ROOT, ManualWorkflow, ObservationError, compile_profile,
                             keys, positive, text, inventory_observations)
from qubit_csv import FORMAT, parse_report

SOURCE = ROOT / 'model/qubit-4-manual.synthetic.json'
STEPS = ['rack_ready', 'workspace_clear', 'claim', 'begin_preparation', 'confirm_preparation', 'place',
         'advance_time', 'begin_measurement', 'confirm_measurement', 'approve_calibration',
         'dispose_vessel', 'import_results', 'review_results', 'release']


def load_profile(source=SOURCE):
    definition = compile_profile(source, 'solidcraftbot.qubit-manual-profile/1', [
        'scripts/qubit_manual.py', 'scripts/qubit_csv.py', 'scripts/manual_results.py',
        'scripts/run_qubit_manual.py', 'scripts/manual_workflow_cli.py',
        'model/qubit-4-manual.schema.json'], extra_fields=('reagents', 'logical_places'))
    p, protocol = definition['profile'], definition['protocol']
    if (protocol['format'] != 'solidcraftbot.qubit-manual-protocol/1'
            or protocol['capability'] != 'fluorometric_assay'
            or protocol['steps'] != STEPS or protocol['return_policy'] != 'original_place'):
        raise TaskError('Unsupported Qubit protocol contract')
    expected = {key: {'unit': unit, 'exclusive_minimum': 0} for key, unit in [
        ('sample_volume_ul', 'uL'), ('standard_volume_ul', 'uL'), ('assay_total_volume_ul', 'uL'),
        ('incubation_min_s', 's'), ('calibration_validity_s', 's'), ('task_deadline_s', 's')]}
    expected['incubation_max_s'] = {'unit': 's', 'exclusive_minimum': 0, 'nullable': True}
    if protocol['parameters'] != expected:
        raise TaskError('Unsupported Qubit parameter contract')
    params = p['parameters']
    if params['assay_total_volume_ul'] <= max(params['sample_volume_ul'], params['standard_volume_ul']):
        raise TaskError('Assay total volume must exceed the transferred volume')
    maximum = params['incubation_max_s']
    if maximum is not None and maximum < params['incubation_min_s']:
        raise TaskError('Inconsistent incubation window')
    if params['task_deadline_s'] <= 2 * params['incubation_min_s']:
        raise TaskError('Task deadline must cover standard and sample incubation')
    assay = protocol['assay']
    keys(assay, 'id revision standards', 'synthetic assay')
    if not text(assay['id'], 'assay id').startswith('SYN.'):
        raise TaskError('The first Qubit assay must be explicitly fictitious')
    text(assay['revision'], 'assay revision')
    standards = assay['standards']
    if not isinstance(standards, list) or len(standards) < 2:
        raise TaskError('At least two declared synthetic standards required')
    for standard in standards:
        keys(standard, 'id stock_id', 'standard')
        for key in standard:
            text(standard[key], 'standard ' + key)
    if len({s['id'] for s in standards}) != len(standards):
        raise TaskError('Duplicate standard id')
    keys(p['reagents'], 'kit_lot standard_lot', 'reagent declarations')
    for value in p['reagents'].values():
        text(value, 'synthetic reagent lot')
    if not isinstance(p['logical_places'], list) or not p['logical_places']:
        raise TaskError('Declared non-geometric tube places required')
    pairs = []
    for place in p['logical_places']:
        keys(place, 'holder_id place_id', 'logical place')
        pairs.append(tuple(text(place[k], k) for k in ['holder_id', 'place_id']))
    if len(set(pairs)) != len(pairs):
        raise TaskError('Duplicate logical place')
    if protocol['result_contract'] != {
            'format': FORMAT, 'identity_column': 'Measurement ID',
            'concentration_units': {'ng/uL': 1, 'ng/mL': 0.001},
            'reported_original_required_volumes': ['Sample Volume uL', 'Assay Total Volume uL']}:
        raise TaskError('Unsupported synthetic Qubit report contract')
    return definition


def calibration_binding(state):
    profile, assay = state['definition']['profile'], state['definition']['protocol']['assay']
    return {'instrument_id': profile['instrument']['id'],
            'instrument_serial': profile['instrument']['serial_number'],
            'assay_id': assay['id'], 'assay_revision': assay['revision'],
            **profile['reagents']}


def next_preparation(state):
    return state['run_id'] + '.A01.P%04d' % (len(state['preparations']) + 1)


class Workflow(ManualWorkflow):
    STATE_FORMAT = 'solidcraftbot.qubit-manual-state/1'
    REPORT_FORMAT = 'solidcraftbot.qubit-manual-report/1'
    STEPS = STEPS
    SOURCE = SOURCE
    RUN_PREFIX = 'SYN-QB-'
    DEADLINE_FIELD = 'deadline_s'
    RECOVERY_COMMANDS = ManualWorkflow.RECOVERY_COMMANDS | {'advance_time'}
    CANCELLING_COMMANDS = ManualWorkflow.CANCELLING_COMMANDS | {'dispose_vessel', 'advance_time'}
    EVENT_CLOCK = True
    load_profile = staticmethod(load_profile)

    @staticmethod
    def _initial_extra(run_id, definition):
        return {'logical_time_s': 0.0, 'derived_vessels': {}, 'preparations': {},
                'transfers': {}, 'active_preparations': {}, 'pending_operation': None,
                'calibration': {'id': run_id + '.A01.C01', 'status': 'pending',
                                'standard_measurements': {}, 'binding_source': 'workflow_record'}}

    def _pending(self, state):
        return state['pending_operation']

    @staticmethod
    def card_extra(state):
        return {'logical_time_s': state['logical_time_s'], 'clock_mode': 'synthetic_events/1',
                'pending_operation': state['pending_operation'], 'next_preparation_id': next_preparation(state),
                'derived_vessels': state['derived_vessels'], 'calibration': state['calibration']}

    def _targets(self, state):
        return {'sample:' + key for key in state['samples']} | {
            'standard:' + s['id'] for s in state['definition']['protocol']['assay']['standards']}

    def _active(self, state, target):
        key = state['active_preparations'].get(target)
        return state['preparations'].get(key) if key else None

    def _begin_preparation(self, state, actor_id, kind, target_id, vessel_id,
                           observed_vessel_id, holder_id, place_id, empty_tube_confirmed):
        self._claimed(state)
        if self._pending(state):
            raise TaskError('Resolve pending operation first')
        target = kind + ':' + target_id
        if target not in self._targets(state):
            raise TaskError('Unknown sample or standard preparation target')
        previous = self._active(state, target)
        if previous:
            if previous['status'] != 'not_performed':
                raise TaskError('A completed preparation cannot be repeated in this run')
            if state['derived_vessels'][previous['vessel_id']]['location']['kind'] != 'discarded':
                raise TaskError('Discard the previous unused tube before a new preparation attempt')
        preparation_id = next_preparation(state)
        expected_vessel = preparation_id + '.Tube'
        if vessel_id != expected_vessel or observed_vessel_id != vessel_id:
            raise ObservationError('Preparation tube identity mismatch')
        if vessel_id in {s['vessel_id'] for s in state['samples'].values()} | set(state['derived_vessels']):
            raise TaskError('Vessel identity was already used')
        self._require(empty_tube_confirmed, 'Identified empty tube confirmation required before intent')
        location = {'kind': 'logical', 'holder_id': holder_id, 'place_id': place_id}
        if {'holder_id': holder_id, 'place_id': place_id} not in state['definition']['profile']['logical_places']:
            raise TaskError('Undeclared logical preparation place')
        if any(v['location'] == location for v in state['derived_vessels'].values()):
            raise TaskError('Logical preparation place is occupied')
        if kind == 'sample':
            sample = self._sample(state, target_id)
            if sample['location'] != {'kind': 'operator', 'actor_id': actor_id}:
                raise TaskError('Hold the original vessel before preparing its assay')
            self._check_withdrawal(state, target_id)
            sample['volume_uncertain'] = True
        measurement_id = preparation_id + '.M01'
        preparation = {'id': preparation_id, 'kind': kind, 'target_id': target_id,
                       'vessel_id': vessel_id, 'measurement_id': measurement_id, 'status': 'intent',
                       'assay': copy.deepcopy(state['definition']['protocol']['assay']),
                       'reagents': copy.deepcopy(state['definition']['profile']['reagents'])}
        state['preparations'][preparation_id] = preparation
        state['active_preparations'][target] = preparation_id
        state['derived_vessels'][vessel_id] = {
            'id': vessel_id, 'kind': kind, 'preparation_id': preparation_id,
            'content_state': 'uncertain', 'location': location, 'disposition_confirmation': None}
        state['resources'].append('vessel:' + vessel_id)
        state['pending_operation'] = {'kind': 'preparation', 'intent_id': uuid.uuid4().hex,
                                      'preparation_id': preparation_id, 'vessel_id': vessel_id}

    def _finish_preparation(self, state, intent_id, observed_vessel_id, volume_ul,
                            assay_total_volume_ul, mixed, observed_sample_id=None,
                            deviation_reason=None):
        pending = self._pending(state)
        if not pending or pending['kind'] != 'preparation' or pending['intent_id'] != intent_id:
            raise TaskError('Stale or unknown preparation intent')
        preparation = state['preparations'][pending['preparation_id']]
        if observed_vessel_id != pending['vessel_id']:
            raise ObservationError('Observed assay/standard tube identity mismatch')
        self._require(mixed, 'Explicit synthetic mixing confirmation required')
        positive(volume_ul, 'transferred volume')
        positive(assay_total_volume_ul, 'assay total volume')
        if assay_total_volume_ul <= volume_ul:
            raise ObservationError('Assay total volume must exceed transferred volume')
        parameters = state['definition']['profile']['parameters']
        expected_volume = parameters['sample_volume_ul' if preparation['kind'] == 'sample' else 'standard_volume_ul']
        if not math.isclose(volume_ul, expected_volume) or not math.isclose(assay_total_volume_ul, parameters['assay_total_volume_ul']):
            text(deviation_reason, 'preparation volume deviation reason')
        if preparation['kind'] == 'sample':
            if observed_sample_id != preparation['target_id']:
                raise ObservationError('Original sample identity mismatch during transfer')
            self._consume(state, preparation['target_id'], volume_ul, deviation_reason)
            source = {'kind': 'sample', 'sample_id': preparation['target_id'],
                      'vessel_id': state['samples'][preparation['target_id']]['vessel_id']}
        else:
            standard = next(s for s in state['definition']['protocol']['assay']['standards']
                            if s['id'] == preparation['target_id'])
            source = {'kind': 'declared_standard_stock', 'stock_id': standard['stock_id']}
        transfer_id = preparation['id'] + '.Transfer'
        state['transfers'][transfer_id] = {
            'id': transfer_id, 'source': source, 'destination_vessel_id': preparation['vessel_id'],
            'volume': {'value': volume_ul, 'unit': 'uL'}, 'actor_id': state['actor_id'],
            'evidence': 'synthetic_input', 'deviation_reason': deviation_reason}
        preparation.update(status='prepared', transfer_id=transfer_id, sample_volume_ul=volume_ul,
                           assay_total_volume_ul=assay_total_volume_ul,
                           prepared_at_s=self._now(state), incubation_basis='confirmation_event',
                           physical_mixing_time_s=None, deviation_reason=deviation_reason)
        state['derived_vessels'][preparation['vessel_id']]['content_state'] = 'prepared'
        state['planned_measurements'][preparation['kind'] + ':' + preparation['target_id']] = preparation['measurement_id']
        state['pending_operation'] = None

    def _confirm_operation(self, state, handler, data):
        self._claimed(state)
        try:
            inspect.signature(handler).bind(state, **data)
        except TypeError as error:
            raise TaskError('Invalid confirmation arguments: ' + str(error)) from error
        handler(state, **data)

    def _confirm_preparation(self, state, actor_id, **data):
        self._confirm_operation(state, self._finish_preparation, data)

    def _calibration_valid(self, state):
        calibration = state['calibration']
        return (calibration['status'] == 'approved'
                and calibration['binding'] == calibration_binding(state)
                and self._now(state) < calibration['valid_until_s'])

    def _incubated(self, state, preparation):
        age = self._now(state) - preparation['prepared_at_s']
        params = state['definition']['profile']['parameters']
        if age < params['incubation_min_s']:
            raise TaskError('Synthetic incubation minimum not reached')
        maximum = params['incubation_max_s']
        if maximum is not None and age > maximum:
            raise TaskError('Synthetic incubation maximum exceeded')

    def _begin_measurement(self, state, actor_id, preparation_id, measurement_id,
                           observed_vessel_id, calibration_id=None):
        self._claimed(state)
        if self._pending(state):
            raise TaskError('Resolve pending operation first')
        preparation = state['preparations'].get(preparation_id)
        if not preparation or preparation['status'] != 'prepared':
            raise TaskError('A confirmed, not yet measured preparation is required')
        if measurement_id != preparation['measurement_id'] or observed_vessel_id != preparation['vessel_id']:
            raise ObservationError('Measurement/preparation/vessel identity mismatch')
        vessel = state['derived_vessels'][observed_vessel_id]
        if vessel['content_state'] != 'prepared' or vessel['location']['kind'] != 'logical':
            raise TaskError('Prepared tube at a declared logical place required')
        self._incubated(state, preparation)
        if preparation['kind'] == 'sample':
            if calibration_id != state['calibration']['id'] or not self._calibration_valid(state):
                raise TaskError('Matching approved unexpired workflow calibration required')
        elif state['calibration']['status'] != 'pending' or calibration_id is not None:
            raise TaskError('Standard measurement must precede calibration approval')
        state['pending_operation'] = {
            'kind': 'measurement', 'intent_id': uuid.uuid4().hex,
            'preparation_id': preparation_id, 'measurement_id': measurement_id,
            'vessel_id': preparation['vessel_id'], 'started_at_s': self._now(state),
            'calibration_id': state['calibration']['id'],
            'calibration_binding': calibration_binding(state), 'binding_source': 'workflow_record'}

    def _finish_measurement(self, state, intent_id, observed_vessel_id, returned_to_holder):
        pending = self._pending(state)
        if not pending or pending['kind'] != 'measurement' or pending['intent_id'] != intent_id:
            raise TaskError('Stale or unknown measurement intent')
        if observed_vessel_id != pending['vessel_id']:
            raise ObservationError('Observed measured tube identity mismatch')
        self._require(returned_to_holder, 'Synthetic loaded/read/returned confirmation required')
        preparation = state['preparations'][pending['preparation_id']]
        invalid = []
        try:
            self._incubated(state, preparation)
        except TaskError:
            invalid.append('incubation_window_exceeded')
        if preparation['kind'] == 'sample' and not self._calibration_valid(state):
            invalid.append('calibration_invalid_at_completion')
        state['measurements'][pending['measurement_id']] = {
            **pending, 'record_type': preparation['kind'], 'target_id': preparation['target_id'],
            'completed_at_s': self._now(state), 'valid': not invalid, 'invalid_reasons': invalid,
            'actor_id': state['actor_id'], 'evidence': 'synthetic_input'}
        preparation['status'] = 'measured'
        state['pending_operation'] = None

    def _confirm_measurement(self, state, actor_id, **data):
        self._confirm_operation(state, self._finish_measurement, data)

    def _approve_calibration(self, state, actor_id, binding, standard_measurements, confirmed, reason):
        self._claimed(state)
        text(reason, 'synthetic calibration decision reason')
        self._require(confirmed, 'Explicit synthetic calibration approval required')
        if self._pending(state) or state['calibration']['status'] != 'pending':
            raise TaskError('One calibration per run; no operation may be pending at approval')
        if binding != calibration_binding(state):
            raise TaskError('Calibration instrument, assay revision or reagent lot mismatch')
        expected = {}
        for standard in state['definition']['protocol']['assay']['standards']:
            preparation = self._active(state, 'standard:' + standard['id'])
            if not preparation or preparation['status'] != 'measured':
                raise TaskError('All declared standard measurements must be confirmed first')
            measurement = state['measurements'][preparation['measurement_id']]
            if not measurement['valid']:
                raise TaskError('Invalid standard measurement cannot approve calibration')
            expected[standard['id']] = preparation['measurement_id']
        if standard_measurements != expected:
            raise TaskError('Calibration standard-to-measurement mapping mismatch')
        last_standard = max(state['measurements'][identity]['completed_at_s'] for identity in expected.values())
        valid_until = last_standard + state['definition']['profile']['parameters']['calibration_validity_s']
        if self._now(state) >= valid_until:
            raise TaskError('Standard evidence expired before calibration approval')
        state['calibration'].update(
            status='approved', binding=copy.deepcopy(binding), standard_measurements=expected,
            approved_at_s=self._now(state),
            last_standard_measured_at_s=last_standard, valid_until_s=valid_until,
            reason=reason, actor_id=actor_id, evidence='synthetic_input')

    def _reconcile_device(self, state, actor_id, calibration_still_valid, pending_resolution=None):
        if type(calibration_still_valid) is not bool:
            raise TaskError('Explicit calibration observation required')
        if not calibration_still_valid and state['calibration']['status'] == 'approved':
            state['calibration']['status'] = 'invalidated_by_observation'
        pending = self._pending(state)
        if pending:
            if not isinstance(pending_resolution, dict) or pending_resolution.get('intent_id') != pending['intent_id']:
                raise TaskError('Explicit matching pending operation outcome required')
            outcome = pending_resolution.get('outcome')
            preparation = state['preparations'][pending['preparation_id']]
            if outcome == 'unknown':
                state['recovery_required'] = 'operation_outcome_unknown'
                return False
            if outcome == 'performed':
                data = {k: v for k, v in pending_resolution.items() if k != 'outcome'}
                handler = self._finish_preparation if pending['kind'] == 'preparation' else self._finish_measurement
                # Validate caller fields before invoking the device transition.
                try:
                    inspect.signature(handler).bind(state, **data)
                except TypeError as error:
                    raise TaskError('Invalid pending resolution: ' + str(error)) from error
                handler(state, **data)
            elif outcome == 'not_performed':
                keys(pending_resolution, 'intent_id outcome', 'pending resolution')
                if pending['kind'] == 'measurement':
                    if state['status'] != 'cancelling':
                        raise TaskError('Cancel the run before retiring an unperformed measurement')
                    preparation['status'] = 'measurement_not_performed'
                else:
                    preparation['status'] = 'not_performed'
                    state['derived_vessels'][preparation['vessel_id']]['content_state'] = 'empty'
                    if preparation['kind'] == 'sample':
                        state['samples'][preparation['target_id']]['volume_uncertain'] = False
                state['pending_operation'] = None
            else:
                raise TaskError('Unknown pending operation outcome')
        elif pending_resolution is not None:
            raise TaskError('No pending operation to resolve')
        return True

    def _before_import(self, state):
        if self._pending(state):
            raise TaskError('Resolve pending operation before importing')
        for target in self._targets(state):
            preparation = self._active(state, target)
            if not preparation or preparation['status'] != 'measured':
                raise TaskError('All sample and standard measurements must be confirmed before import')
        if not state['calibration'].get('standard_measurements'):
            raise TaskError('Calibration approval required before final import')

    def _expected_results(self, state):
        return set(state['planned_measurements'].values())

    def _parse_import(self, state, artifact, origin):
        report = parse_report(artifact)
        issues, results = [], {}
        ids = [row['measurement_id'] for row in report['rows']]
        expected = self._expected_results(state)
        if len(ids) != len(set(ids)):
            issues.append('duplicate_measurement')
        if set(ids) - expected:
            issues.append('foreign_measurement')
        if expected - set(ids):
            issues.append('missing_measurement')
        binding = calibration_binding(state)
        metadata = {'assayid': binding['assay_id'], 'assayrevision': binding['assay_revision'],
                    'kitlot': binding['kit_lot'], 'standardlot': binding['standard_lot'],
                    'instrumentserial': binding['instrument_serial']}
        for row in report['rows']:
            identity = row['measurement_id']
            if identity not in expected:
                continue
            measurement = state['measurements'][identity]
            preparation = state['preparations'][measurement['preparation_id']]
            if not measurement['valid']:
                issues.append('invalid_measurement')
            if row['record_type'] != preparation['kind']:
                issues.append('record_type_mismatch')
            for key, expected_value in {**metadata, 'vesselid': preparation['vessel_id']}.items():
                if key in row['metadata'] and row['metadata'][key] != expected_value:
                    issues.append(key + '_mismatch')
            volume = row['reported_sample_volume_ul']
            if volume is not None and not math.isclose(volume, preparation['sample_volume_ul'], rel_tol=1e-9):
                issues.append('sample_volume_mismatch')
            original = None
            if preparation['kind'] == 'sample':
                if row['original_concentration'] is not None:
                    total_volume = row['reported_assay_total_volume_ul']
                    if (volume is None or total_volume is None
                            or not math.isclose(volume, preparation['sample_volume_ul'], rel_tol=1e-9)):
                        issues.append('dilution_basis_unverified')
                    if (total_volume is not None and not math.isclose(
                            total_volume, preparation['assay_total_volume_ul'], rel_tol=1e-9)):
                        issues.append('assay_total_volume_mismatch')
                    original = {**row['original_concentration'], 'basis': 'reported'}
                else:
                    concentration = row['tube_concentration']['value'] * preparation['assay_total_volume_ul'] / preparation['sample_volume_ul']
                    if not math.isfinite(concentration):
                        raise TaskError('Non-finite derived original concentration')
                    original = {'value': concentration, 'unit': 'ng/uL', 'basis': 'derived',
                                'formula': 'tube_concentration_ng_ul * assay_total_volume_ul / sample_volume_ul',
                                'assay_total_volume_ul': preparation['assay_total_volume_ul'],
                                'sample_volume_ul': preparation['sample_volume_ul'],
                                'tube_unit_factor': row['tube_concentration']['unit_factor']}
            results[identity] = {
                **row, 'preparation_id': preparation['id'], 'vessel_id': preparation['vessel_id'],
                'sample_id': preparation['target_id'] if preparation['kind'] == 'sample' else None,
                'standard_id': preparation['target_id'] if preparation['kind'] == 'standard' else None,
                'transfer_id': preparation['transfer_id'], 'calibration_id': measurement['calibration_id'],
                'calibration_binding_source': 'workflow_record',
                'calibration_binding': measurement['calibration_binding'],
                'metrics': {'tube_concentration': {**row['tube_concentration'], 'basis': 'reported'},
                            'original_concentration': original},
                'metadata_sources': {key: 'synthetic_report' if key in row['metadata'] else 'workflow_declaration'
                                     for key in metadata},
                'artifact_sha256': digest(artifact), 'origin': origin}
        return report, issues, results

    def _scientific_ready(self, state):
        self._before_import(state)
        if state['calibration']['status'] != 'approved':
            raise TaskError('Calibration was not approved or was invalidated')
        if any(not measurement['valid'] for measurement in state['measurements'].values()):
            raise TaskError('Invalid completed measurement blocks result acceptance')

    def _report(self, state, trace):
        report = super()._report(state, trace)
        report.update(clock_mode='synthetic_events/1', logical_time_s=state['logical_time_s'],
                      derived_vessels=state['derived_vessels'], preparations=state['preparations'],
                      transfers=state['transfers'], calibration=state['calibration'],
                      calibration_curve_computed=False, cross_run_volume_ledger=False,
                      external_device_recalibration_detectable=False)
        return report
