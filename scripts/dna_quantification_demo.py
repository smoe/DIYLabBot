"""Explicit synthetic execution of the persisted NanoDrop -> Qubit DNA plan.

Only SyntheticBackend manufactures positive observations and report bytes.
This module neither sends device commands nor treats a planned dilution as a
performed transfer. Every state change goes through the coordinator/handles.
"""
import csv
import io
import math

from manual_tasks import TaskError
from manual_workflow import text
from qubit_csv import FORMAT as QUBIT_FORMAT
from qubit_manual import calibration_binding, next_preparation


ACTOR = 'SYN.DNA.Operator01'
PRESETS = ('none', '1+9', '1+19')


class SyntheticBackend:
    """Fictitious independent instrument values, not a hardware adapter."""
    mode = 'synthetic_only'

    def __init__(self, original_concentrations=None, *, qubit_report_original=False, actor_id=ACTOR):
        self.actor_id = text(actor_id, 'synthetic DNA actor id')
        self.original_concentrations = {'nanodrop': 50.0, 'qubit': 48.0}
        if original_concentrations is not None:
            if not isinstance(original_concentrations, dict) or set(original_concentrations) != {'nanodrop', 'qubit'}:
                raise TaskError('Separate synthetic NanoDrop and Qubit concentrations required')
            self.original_concentrations = dict(original_concentrations)
        for value in self.original_concentrations.values():
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise TaskError('Finite nonnegative synthetic original concentrations required')
        if type(qubit_report_original) is not bool:
            raise TaskError('Explicit synthetic Qubit reporting mode required')
        self.qubit_report_original = qubit_report_original

    def accept_rack(self, flow):
        flow.accept_rack(self.actor_id, flow.inventory_observations(),
                         workspace_clear=True, rack_on_table_confirmed=True)

    def confirm_dilution(self, flow):
        pending = flow.state['pending_dilution']
        if not pending:
            raise TaskError('No pending synthetic dilution')
        flow.confirm_dilution(self.actor_id, intent_id=pending['intent_id'],
            observed_source_vessel_id=pending['source_vessel_id'],
            observed_target_vessel_id=pending['target_vessel_id'],
            sample_volume_ul=pending['planned_sample_volume_ul'],
            diluent_volume_ul=pending['planned_diluent_volume_ul'],
            mixed=True, source_returned=True)

    def _input_concentration(self, flow, context_id):
        root = flow.state
        context = root['contexts'][context_id]
        factor = root['attempts'][context['attempt_id']]['external_factor']
        if type(factor) not in (int, float) or not math.isfinite(factor) or factor < 1:
            raise TaskError('Confirmed external dilution factor required before a synthetic measurement')
        # Each device has its own synthetic truth. Qubit never copies NanoDrop.
        return self.original_concentrations[context['device']] / factor

    def _claim(self, handle):
        state = handle.state
        if state['status'] != 'ready' or state['actor_id'] is not None:
            raise TaskError('Synthetic execution needs a fresh device context; reconcile interrupted work first')
        handle.act('workspace_clear', self.actor_id, confirmed=True)
        handle.act('claim', self.actor_id)

    def _take(self, handle, sample_id):
        state = handle.state
        sample = state['samples'][sample_id]
        handle.act('take', self.actor_id, sample_id=sample_id, observed_sample_id=sample_id,
                   rack_id=sample['location']['rack_id'], place_id=sample['original_place_id'])

    def _place(self, handle, sample_id):
        state = handle.state
        sample = state['samples'][sample_id]
        handle.act('place', self.actor_id, sample_id=sample_id, observed_sample_id=sample_id,
                   rack_id=state['definition']['profile']['rack']['id'],
                   place_id=sample['original_place_id'])

    def nanodrop_report(self, flow, context_id):
        state = flow.stage(context_id).state
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['Application', state['definition']['protocol']['method']])
        writer.writerow(['Serial Number', state['definition']['profile']['instrument']['serial_number']])
        writer.writerow(['Sample Name', 'ng/uL', 'Factor', 'Warnings'])
        for identity in state['planned_measurements'].values():
            # Factor 50 is a raw NanoDrop cell. It is NOT external predilution.
            writer.writerow([identity, self._input_concentration(flow, context_id), 50, ''])
        return stream.getvalue().encode('utf-8')

    def _run_nanodrop(self, flow, context_id, pause_after):
        handle = flow.stage(context_id)
        self._claim(handle)
        handle.act('blank', self.actor_id, reference_id='SYN.DNA.Blank01', cleaned=True)
        sample_id = next(iter(handle.state['samples']))
        self._take(handle, sample_id)
        handle.act('begin_measurement', self.actor_id, sample_id=sample_id,
                   measurement_id=handle.state['planned_measurements'][sample_id])
        if pause_after == 'measurement_intent':
            return False
        state = handle.state
        handle.act('confirm_measurement', self.actor_id,
                   intent_id=state['pending_measurement']['intent_id'],
                   observed_sample_id=sample_id,
                   volume_ul=state['definition']['profile']['parameters']['sample_volume_ul'],
                   cleaned=True)
        self._place(handle, sample_id)
        handle.import_content(self.nanodrop_report(flow, context_id), self.actor_id,
                              context_id + '.synthetic-nanodrop.csv')
        flow.finish_context(self.actor_id, context_id, workspace_clear=True)
        return True

    def _begin_preparation(self, handle, kind, target_id):
        state = handle.state
        profile = state['definition']['profile']
        occupied = [vessel['location'] for vessel in state['derived_vessels'].values()
                    if vessel['location']['kind'] != 'discarded']
        places = [place for place in profile['logical_places']
                  if place['holder_id'] != profile['instrument']['id']]
        place = next((place for place in places if {'kind': 'logical', **place} not in occupied), None)
        if place is None:
            raise TaskError('No declared synthetic assay-holder place is available')
        identity = next_preparation(state) + '.Tube'
        handle.act('begin_preparation', self.actor_id, kind=kind, target_id=target_id,
                   vessel_id=identity, observed_vessel_id=identity,
                   empty_tube_confirmed=True, **place)
        return handle.state['pending_operation']['preparation_id']

    def _confirm_preparation(self, handle):
        state = handle.state
        pending = state['pending_operation']
        preparation = state['preparations'][pending['preparation_id']]
        params = state['definition']['profile']['parameters']
        handle.act('confirm_preparation', self.actor_id, intent_id=pending['intent_id'],
                   observed_vessel_id=pending['vessel_id'],
                   observed_sample_id=preparation['target_id'] if preparation['kind'] == 'sample' else None,
                   volume_ul=params['sample_volume_ul' if preparation['kind'] == 'sample' else 'standard_volume_ul'],
                   assay_total_volume_ul=params['assay_total_volume_ul'], mixed=True)

    def _measure_qubit(self, handle, preparation_id, pause_after=None):
        state = handle.state
        preparation = state['preparations'][preparation_id]
        handle.act('begin_measurement', self.actor_id, preparation_id=preparation_id,
                   measurement_id=preparation['measurement_id'], observed_vessel_id=preparation['vessel_id'],
                   calibration_id=state['calibration']['id'] if preparation['kind'] == 'sample' else None)
        if pause_after == 'measurement_intent':
            return False
        handle.act('confirm_measurement', self.actor_id,
                   intent_id=handle.state['pending_operation']['intent_id'],
                   observed_vessel_id=preparation['vessel_id'], returned_to_holder=True)
        return True

    def _dispose_context_tubes(self, handle):
        for identity, vessel in list(handle.state['derived_vessels'].items()):
            if vessel['location']['kind'] != 'discarded':
                handle.act('dispose_vessel', self.actor_id, vessel_id=identity, observed_vessel_id=identity,
                           reason='Explicit synthetic DNA assay/standard tube disposal')

    def qubit_report(self, flow, context_id):
        state = flow.stage(context_id).state
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['Format', QUBIT_FORMAT])
        writer.writerow(['Measurement ID', 'Record Type', 'Vessel ID', 'Assay ID', 'Assay Revision',
                         'Kit Lot', 'Standard Lot', 'Instrument Serial', 'Tube Concentration', 'Tube Unit',
                         'Original Concentration', 'Original Unit', 'Sample Volume uL',
                         'Assay Total Volume uL', 'Warnings'])
        binding = calibration_binding(state)
        standard_index = 0
        for measurement in state['measurements'].values():
            preparation = state['preparations'][measurement['preparation_id']]
            if preparation['kind'] == 'sample':
                original = self._input_concentration(flow, context_id)
                tube = original * preparation['sample_volume_ul'] / preparation['assay_total_volume_ul']
                supplied = self.qubit_report_original
            else:
                # Fictitious standard observations, not a calibration curve.
                tube = float(standard_index) / 2
                standard_index += 1
                original, supplied = None, False
            writer.writerow([measurement['measurement_id'], preparation['kind'], preparation['vessel_id'],
                binding['assay_id'], binding['assay_revision'], binding['kit_lot'], binding['standard_lot'],
                binding['instrument_serial'], tube, 'ng/uL', original if supplied else '',
                'ng/uL' if supplied else '', preparation['sample_volume_ul'],
                preparation['assay_total_volume_ul'], ''])
        return stream.getvalue().encode('utf-8')

    def _run_qubit(self, flow, context_id, pause_after):
        handle = flow.stage(context_id)
        self._claim(handle)
        standards = handle.state['definition']['protocol']['assay']['standards']
        prepared = []
        for standard in standards:
            identity = self._begin_preparation(handle, 'standard', standard['id'])
            self._confirm_preparation(handle)
            prepared.append(identity)
        flow.advance_time(self.actor_id, handle.state['definition']['profile']['parameters']['incubation_min_s'])
        for identity in prepared:
            if not self._measure_qubit(handle, identity, pause_after):
                return False
        state = handle.state
        mapping = {preparation['target_id']: preparation['measurement_id']
                   for preparation in state['preparations'].values() if preparation['kind'] == 'standard'}
        handle.act('approve_calibration', self.actor_id, binding=calibration_binding(state),
                   standard_measurements=mapping, confirmed=True,
                   reason='Explicit synthetic DNA-HS calibration approval; no measured calibration curve')
        self._dispose_context_tubes(handle)
        sample_id = next(iter(handle.state['samples']))
        self._take(handle, sample_id)
        identity = self._begin_preparation(handle, 'sample', sample_id)
        self._confirm_preparation(handle)
        self._place(handle, sample_id)
        flow.advance_time(self.actor_id, handle.state['definition']['profile']['parameters']['incubation_min_s'])
        if not self._measure_qubit(handle, identity, pause_after):
            return False
        self._dispose_context_tubes(handle)
        handle.import_content(self.qubit_report(flow, context_id), self.actor_id,
                              context_id + '.synthetic-qubit.csv')
        flow.finish_context(self.actor_id, context_id, workspace_clear=True)
        return True

    def run_context(self, flow, context_id, pause_after=None):
        device = flow.state['contexts'][context_id]['device']
        if device == 'nanodrop':
            return self._run_nanodrop(flow, context_id, pause_after)
        if device == 'qubit':
            return self._run_qubit(flow, context_id, pause_after)
        raise TaskError('Unsupported synthetic device context')

    def finish_run(self, flow):
        for identity, vessel in flow.state['inventory']['vessels'].items():
            if vessel.get('kind') == 'dilution' and vessel['location']['kind'] != 'discarded':
                flow.dispose_material(self.actor_id, identity, observed_vessel_id=identity,
                    reason='Explicit synthetic disposal of remaining dilution material')
        flow.complete(self.actor_id, flow.inventory_observations(), workspace_clear=True)


def run_synthetic(flow, initial_dilution='none', after_range=None, backend=None, pause_after=None):
    """Run fresh synthetic steps, stopping at a choice or an uncertain intent.

    An unused offered retry can run once; the root retains which factors were
    already tried. This driver never changes raw results or replays an intent
    left by an interrupted execution.
    """
    if initial_dilution not in PRESETS or after_range is not None and after_range not in PRESETS:
        raise TaskError('Choose none, 1+9 or 1+19')
    if pause_after not in {None, 'dilution_intent', 'measurement_intent'}:
        raise TaskError('Unknown synthetic pause point')
    backend = SyntheticBackend() if backend is None else backend
    if not isinstance(backend, SyntheticBackend) or backend.mode != 'synthetic_only':
        raise TaskError('Only an explicit SyntheticBackend can execute this preparation')
    state = flow.state
    if state.get('recovery_required') or state['status'] == 'held':
        raise TaskError('Explicit inventory/intent reconciliation required before synthetic continuation')
    if state.get('pending_dilution'):
        raise TaskError('An existing dilution intent requires explicit reconciliation; it is not replayed')
    if state['status'] == 'created':
        backend.accept_rack(flow)
    while True:
        state = flow.state
        if state['status'] in {'completed', 'cancelled', 'held'}:
            return state
        if state.get('recovery_required'):
            raise TaskError('Reconciliation required before further synthetic effects')
        context_id = state.get('active_context_id')
        if context_id:
            if not backend.run_context(flow, context_id, pause_after):
                return flow.state
            continue
        sample_id = state.get('current_sample_id')
        if sample_id is None:
            backend.finish_run(flow)
            return flow.state
        attempt_id = state.get('active_attempt_id')
        if not attempt_id:
            chosen = initial_dilution
        elif state['status'] == 'awaiting_decision':
            attempt = state['attempts'][attempt_id]
            evaluations = attempt.get('evaluations', {})
            if set(evaluations) == {'nanodrop', 'qubit'} and all(
                    result['status'] == 'in_range' for result in evaluations.values()):
                flow.accept_result(backend.actor_id, sample_id, reason='Explicit synthetic acceptance of both in-range measurements')
                continue
            chosen = after_range
        elif state['status'] == 'awaiting_choice':
            chosen = after_range
        else:
            raise TaskError('No executable synthetic step is available')
        choices = {option['key'] for option in flow.options(sample_id)}
        if chosen is None or chosen not in choices:
            return flow.state
        flow.choose_dilution(backend.actor_id, sample_id, chosen)
        if flow.state.get('pending_dilution'):
            if pause_after == 'dilution_intent':
                return flow.state
            backend.confirm_dilution(flow)
