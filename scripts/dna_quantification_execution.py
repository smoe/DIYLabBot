"""Resume confirmed synthetic device operations for the network coordinator.

This backend reads the canonical root and existing device contexts. A pending
operation always needs explicit root reconciliation. Completed preparation,
measurement and import identities are retained rather than executed again.
The separate local demo keeps its fresh-context-only behavior.
"""
from dna_quantification_demo import SyntheticBackend
from dna_quantification_tasks import MockTaskWorker
from manual_tasks import TaskError
from qubit_manual import calibration_binding


class SyntheticHandling:
    """Legacy synthetic person handling, reusing its existing implementation."""
    def take(self, backend, handle, sample_id):
        return SyntheticBackend._take(backend, handle, sample_id)

    def place(self, backend, handle, sample_id):
        return SyntheticBackend._place(backend, handle, sample_id)


class MockTaskHandling(SyntheticHandling):
    """Separate worker assertion and explicit synthetic root observation."""
    def __init__(self, agent_id='SYN.DNA.HandlingAgent01', worker=None):
        self.worker = MockTaskWorker(agent_id) if worker is None else worker
        if self.worker.agent_id != agent_id:
            raise TaskError('Handling worker must match the assigned executing agent')
        self.agent_id = agent_id

    def _transfer(self, backend, handle, sample_id, target):
        flow = handle.flow; root = flow.state
        if root.get('task_port', {}).get('pending_goal_id'):
            raise TaskError('Existing worker task requires explicit root reconciliation; it is not replayed')
        context = root['contexts'][handle.context_id]
        if context['sample_id'] != sample_id:
            raise TaskError('Task handling sample does not match the active context')
        goal = flow.task_goal(handle.context_id, target, self.agent_id)
        flow.intend_task(backend.actor_id, goal)
        flow.dispatch_task(backend.actor_id, goal['goal_id'], self.worker)
        # B0 deliberately manufactures this confirmation in the explicitly
        # synthetic backend, never from a worker's evidence classification.
        flow.observe_task(backend.actor_id, goal['goal_id'],
            {'sample_id': sample_id, 'vessel_id': context['source_vessel_id'], 'location': target},
            evidence='synthetic_backend')

    def take(self, backend, handle, sample_id):
        return self._transfer(backend, handle, sample_id, {'kind': 'agent', 'agent_id': self.agent_id})

    def place(self, backend, handle, sample_id):
        root = handle.flow.state; context = root['contexts'][handle.context_id]
        home = root['inventory']['vessels'][context['source_vessel_id']]['home']
        return self._transfer(backend, handle, sample_id, home)


class SyntheticMeasurementProvider:
    """Generate independent fictitious reports using the existing one source."""
    def nanodrop_report(self, backend, flow, context_id):
        return SyntheticBackend.nanodrop_report(backend, flow, context_id)

    def qubit_report(self, backend, flow, context_id):
        return SyntheticBackend.qubit_report(backend, flow, context_id)


class NetworkSyntheticBackend(SyntheticBackend):
    """Synthetic continuation only; not a network, hardware or motion driver."""
    def __init__(self, *args, handling=None, measurement_provider=None,
                 executing_agent_id='SYN.DNA.HandlingAgent01', **kwargs):
        super().__init__(*args, **kwargs)
        self.handling = MockTaskHandling(executing_agent_id) if handling is None else handling
        self.measurement_provider = SyntheticMeasurementProvider() if measurement_provider is None else measurement_provider
        if not isinstance(self.handling, SyntheticHandling) or not isinstance(self.measurement_provider, SyntheticMeasurementProvider):
            raise TaskError('Explicit synthetic handling and measurement providers required')

    def _take(self, handle, sample_id):
        return self.handling.take(self, handle, sample_id)

    def _place(self, handle, sample_id):
        return self.handling.place(self, handle, sample_id)

    def nanodrop_report(self, flow, context_id):
        return self.measurement_provider.nanodrop_report(self, flow, context_id)

    def qubit_report(self, flow, context_id):
        return self.measurement_provider.qubit_report(self, flow, context_id)

    def _continue_context(self, flow, context_id):
        root = flow.state
        if (root.get('active_context_id') != context_id or root.get('recovery_required')
                or root.get('cancel_requested') or root['status'] != 'running'):
            raise TaskError('Active reconciled device context required for synthetic continuation')
        if root.get('task_port', {}).get('pending_goal_id'):
            raise TaskError('Explicit root reconciliation required for the pending worker task')
        handle = flow.stage(context_id); state = handle.state
        if state.get('pending_measurement') or state.get('pending_operation'):
            raise TaskError('Explicit root reconciliation required for the pending operation')
        if state['status'] == 'ready' and state['actor_id'] is None:
            self._claim(handle)
        elif state['status'] != 'working' or state['actor_id'] != self.actor_id:
            raise TaskError('Existing device context is not held by this synthetic actor')
        return handle

    def _ensure_held(self, handle, sample_id):
        state = handle.state; sample = state['samples'][sample_id]
        if sample['location'] == {'kind': 'operator', 'actor_id': self.actor_id}:
            return
        home = {'kind': 'rack', 'rack_id': state['definition']['profile']['rack']['id'],
                'place_id': sample['original_place_id']}
        if sample['location'] != home:
            raise TaskError('Explicit source-custody observation required before continuation')
        self._take(handle, sample_id)

    def _ensure_returned(self, handle, sample_id):
        state = handle.state; sample = state['samples'][sample_id]
        home = {'kind': 'rack', 'rack_id': state['definition']['profile']['rack']['id'],
                'place_id': sample['original_place_id']}
        if sample['location'] == home and sample['return_confirmation']:
            return
        if sample['location'] != {'kind': 'operator', 'actor_id': self.actor_id}:
            raise TaskError('Explicit source-return observation required before continuation')
        self._place(handle, sample_id)

    def _import_if_needed(self, flow, context_id, handle, device):
        state = handle.state
        if any(record['status'] == 'quarantined' for record in state['imports'].values()):
            raise TaskError('Resolve quarantined device imports explicitly before continuation')
        expected = set(state['planned_measurements'].values())
        if set(state['results']) == expected:
            return
        if state['results']:
            raise TaskError('Incomplete identified device results need explicit review')
        raw = self.nanodrop_report(flow, context_id) if device == 'nanodrop' else self.qubit_report(flow, context_id)
        handle.import_content(raw, self.actor_id, context_id + '.synthetic-' + device + '.csv')

    def _run_nanodrop(self, flow, context_id, pause_after):
        handle = self._continue_context(flow, context_id)
        sample_id = next(iter(handle.state['samples']))
        measurement_id = handle.state['planned_measurements'][sample_id]
        if measurement_id not in handle.state['measurements']:
            if not handle.state['active_blank']:
                handle.act('blank', self.actor_id, reference_id='SYN.DNA.Blank01', cleaned=True)
            self._ensure_held(handle, sample_id)
            handle.act('begin_measurement', self.actor_id, sample_id=sample_id, measurement_id=measurement_id)
            if pause_after == 'measurement_intent':
                return False
            handle.act('confirm_measurement', self.actor_id,
                intent_id=handle.state['pending_measurement']['intent_id'], observed_sample_id=sample_id,
                volume_ul=handle.state['definition']['profile']['parameters']['sample_volume_ul'], cleaned=True)
        self._ensure_returned(handle, sample_id)
        self._import_if_needed(flow, context_id, handle, 'nanodrop')
        flow.finish_context(self.actor_id, context_id, workspace_clear=True)
        return True

    @staticmethod
    def _active_preparation(handle, kind, target_id):
        state = handle.state
        identity = state['active_preparations'].get(kind + ':' + target_id)
        return state['preparations'].get(identity) if identity else None

    def _prepare_if_needed(self, handle, kind, target_id):
        preparation = self._active_preparation(handle, kind, target_id)
        if preparation is not None and preparation['status'] in {'prepared', 'measured'}:
            return preparation['id']
        if preparation is not None:
            if preparation['status'] != 'not_performed':
                raise TaskError('Unresolved preparation history requires explicit reconciliation')
            vessel_id = preparation['vessel_id']; vessel = handle.state['derived_vessels'][vessel_id]
            if vessel['location']['kind'] != 'discarded':
                handle.act('dispose_vessel', self.actor_id, vessel_id=vessel_id, observed_vessel_id=vessel_id,
                           reason='Explicit synthetic disposal of a reconciled unused preparation tube')
        if kind == 'sample':
            self._ensure_held(handle, target_id)
        identity = self._begin_preparation(handle, kind, target_id)
        self._confirm_preparation(handle)
        return identity

    def _incubate_remaining(self, flow, handle, identities):
        state = handle.state
        minimum = state['definition']['profile']['parameters']['incubation_min_s']
        remaining = max([0] + [minimum - (state['logical_time_s'] - state['preparations'][identity]['prepared_at_s'])
            for identity in identities if state['preparations'][identity]['status'] != 'measured'])
        if remaining > 0:
            flow.advance_time(self.actor_id, remaining)

    def _dispose_kind(self, handle, kind=None):
        for vessel_id, vessel in list(handle.state['derived_vessels'].items()):
            if (kind is None or vessel['kind'] == kind) and vessel['location']['kind'] != 'discarded':
                handle.act('dispose_vessel', self.actor_id, vessel_id=vessel_id, observed_vessel_id=vessel_id,
                           reason='Explicit synthetic DNA assay/standard tube disposal')

    def _require_calibration(self, handle, *, needs_measurement):
        state = handle.state; calibration = state['calibration']
        if (calibration['status'] != 'approved' or calibration.get('binding') != calibration_binding(state)
                or needs_measurement and state['logical_time_s'] >= calibration['valid_until_s']):
            raise TaskError('Explicit approved, matching and unexpired calibration required; no automatic renewal')

    def _run_qubit(self, flow, context_id, pause_after):
        handle = self._continue_context(flow, context_id)
        calibration = handle.state['calibration']
        if calibration['status'] not in {'pending', 'approved'}:
            raise TaskError('Calibration was invalidated; no automatic replacement approval')
        sample_id = next(iter(handle.state['samples']))
        sample_preparation = self._active_preparation(handle, 'sample', sample_id)
        if calibration['status'] == 'approved':
            self._require_calibration(handle, needs_measurement=not sample_preparation or sample_preparation['status'] != 'measured')
        else:
            standards = handle.state['definition']['protocol']['assay']['standards']
            prepared = [self._prepare_if_needed(handle, 'standard', standard['id']) for standard in standards]
            self._incubate_remaining(flow, handle, prepared)
            for identity in prepared:
                if handle.state['preparations'][identity]['status'] == 'measured':
                    continue
                if not self._measure_qubit(handle, identity, pause_after):
                    return False
            state = handle.state
            mapping = {standard['id']: self._active_preparation(handle, 'standard', standard['id'])['measurement_id']
                       for standard in standards}
            handle.act('approve_calibration', self.actor_id, binding=calibration_binding(state),
                standard_measurements=mapping, confirmed=True,
                reason='Explicit synthetic DNA-HS calibration approval; recorded standards are retained')
        # A resumed sample preparation may already exist. Dispose only standards
        # here, so its still-unmeasured assay tube remains available.
        self._dispose_kind(handle, 'standard')
        identity = self._prepare_if_needed(handle, 'sample', sample_id)
        self._ensure_returned(handle, sample_id)
        if handle.state['preparations'][identity]['status'] != 'measured':
            self._require_calibration(handle, needs_measurement=True)
            self._incubate_remaining(flow, handle, [identity])
            if not self._measure_qubit(handle, identity, pause_after):
                return False
        self._dispose_kind(handle)
        self._import_if_needed(flow, context_id, handle, 'qubit')
        flow.finish_context(self.actor_id, context_id, workspace_clear=True)
        return True
