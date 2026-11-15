"""Resumable synthetic execution of one already-created extraction Root.

Persisted domain state determines which confirmed steps remain. Open effects
are never replayed or resolved from a server-generated inventory observation.
"""
from extraction_analytics_demo import SyntheticExtractionBackend, ACTOR, _DevicePort
from extraction_demo import perform_phase, actual_inputs, REASON
from manual_tasks import TaskError, digest
from qubit_manual import calibration_binding
from tapestation_results import synthetic_report


class ExecutionDriver:
    def __init__(self, flow, pause=None):
        self.flow, self.pause = flow, pause
        self.backend = SyntheticExtractionBackend(actor_id=ACTOR)
        self.port = _DevicePort(flow)
        self.flow.checkpoint_callback = self._checkpoint

    def _checkpoint(self, command, arguments):
        point = None
        if command == 'begin_phase':
            step = self.flow._step(self.flow.state, arguments['phase_id'])
            if step['kind'] == 'effect': point = 'phase_intent'
        if command == 'device_action':
            if arguments['device'] == 'nanodrop' and arguments['operation'] == 'begin_measurement': point = 'nanodrop_intent'
            if arguments['device'] == 'qubit' and arguments['operation'] == 'begin_preparation': point = 'qubit_preparation_intent'
        if command == 'confirm_tapestation_loaded': point = 'tapestation_loaded'
        if point and self.pause: self.pause(point, self.flow)

    def _act(self, command, **data): return self.flow.act(command, ACTOR, **data)

    def run(self):
        state = self.flow.state
        if state['status'] == 'completed': return
        if state['status'] == 'cancelled' or state['status'] == 'cancelling': raise TaskError('Cancelled extraction work cannot resume')
        if state['recovery_required'] or self.flow._pending(state): raise TaskError('Explicit pending-effect and inventory reconciliation required')
        if state['process']['deviations'] or state['process']['aborted_phase']: raise TaskError('Process deviations require controlled abort')
        if state['status'] == 'created': self._act('accept_inventory', observations=self.flow.inventory_observations())
        state = self.flow.state
        if state['actor_id'] is None:
            self._act('workspace_clear', confirmed=True); self._act('claim')
        definition = self.flow.state['definition']; execution = definition['execution']
        sample = next(iter(execution['samples']))
        while self.flow.state['process']['cursor'] < len(execution['steps']):
            step = execution['steps'][self.flow.state['process']['cursor']]
            perform_phase(self.flow, sample, step, actor_id=ACTOR)
        for device in ('nanodrop', 'qubit'):
            stage = self.flow.state['analytics']['stages'].get(device)
            if stage is not None and stage['local']['status'] == 'completed': continue
            if stage is None: self._act('start_device', device=device)
            self._nanodrop() if device == 'nanodrop' else self._qubit()
        self._tapestation()

    def _claim(self, handle):
        if handle.state['actor_id'] is None: self.backend._claim(handle)

    def _place_source(self, handle, sample):
        location = handle.state['samples'][sample]['location']
        if location == {'kind': 'operator', 'actor_id': ACTOR}: self.backend._place(handle, sample)
        elif location != self.flow.state['definition']['execution']['analytics']['product_home']:
            raise TaskError('The DNA source is not at its original place or held by the fixture actor')

    def _nanodrop(self):
        handle = self.flow.device('nanodrop'); self._claim(handle)
        sample = next(iter(handle.state['samples']))
        if not handle.state['measurements']:
            if handle.state['active_blank'] is None: handle.act('blank', ACTOR, reference_id='SYN.DNA.Blank01', cleaned=True)
            if handle.state['samples'][sample]['location']['kind'] == 'rack': self.backend._take(handle, sample)
            handle.act('begin_measurement', ACTOR, sample_id=sample, measurement_id=handle.state['planned_measurements'][sample])
            handle.act('confirm_measurement', ACTOR, intent_id=handle.state['pending_measurement']['intent_id'],
                observed_sample_id=sample, volume_ul=handle.state['definition']['profile']['parameters']['sample_volume_ul'], cleaned=True)
        self._place_source(handle, sample)
        if not handle.state['imports']:
            handle.import_content(self.backend.nanodrop_report(self.port, 'nanodrop'), ACTOR, 'synthetic-nanodrop.csv')
        self.port.finish_context(ACTOR, 'nanodrop', workspace_clear=True)

    def _incubate(self, handle, preparation_id):
        local = handle.state
        preparation = local['preparations'][preparation_id]
        remaining = local['definition']['profile']['parameters']['incubation_min_s'] - (
            local['logical_time_s'] - preparation['prepared_at_s'])
        if remaining > 0: self._act('advance_time', seconds=remaining)

    def _prepare(self, handle, kind, target):
        state = handle.state
        identity = state['active_preparations'].get(kind + ':' + target)
        if identity is None:
            identity = self.backend._begin_preparation(handle, kind, target)
            self.backend._confirm_preparation(handle)
        if handle.state['preparations'][identity]['status'] not in {'prepared', 'measured'}:
            raise TaskError('An uncertain or retired Qubit preparation cannot be automatically repeated')
        return identity

    def _measure(self, handle, identity):
        if handle.state['preparations'][identity]['status'] == 'prepared':
            self._incubate(handle, identity); self.backend._measure_qubit(handle, identity)

    @staticmethod
    def _dispose(handle, vessel_id):
        if handle.state['derived_vessels'][vessel_id]['location']['kind'] != 'discarded':
            handle.act('dispose_vessel', ACTOR, vessel_id=vessel_id, observed_vessel_id=vessel_id, reason=REASON)

    def _qubit(self):
        handle = self.flow.device('qubit'); self._claim(handle)
        standards = handle.state['definition']['protocol']['assay']['standards']
        for standard in standards:
            identity = self._prepare(handle, 'standard', standard['id']); self._measure(handle, identity)
        state = handle.state
        if state['calibration']['status'] == 'pending':
            mapping = {p['target_id']: p['measurement_id'] for p in state['preparations'].values() if p['kind'] == 'standard'}
            handle.act('approve_calibration', ACTOR, binding=calibration_binding(state), standard_measurements=mapping,
                confirmed=True, reason=REASON)
        for preparation in list(handle.state['preparations'].values()):
            if preparation['kind'] == 'standard': self._dispose(handle, preparation['vessel_id'])
        sample = next(iter(handle.state['samples']))
        if 'sample:' + sample not in handle.state['active_preparations']:
            if handle.state['samples'][sample]['location']['kind'] == 'rack': self.backend._take(handle, sample)
        identity = self._prepare(handle, 'sample', sample)
        self._place_source(handle, sample); self._measure(handle, identity)
        self._dispose(handle, handle.state['preparations'][identity]['vessel_id'])
        if not handle.state['imports']:
            handle.import_content(self.backend.qubit_report(self.port, 'qubit'), ACTOR, 'synthetic-qubit.csv')
        self.port.finish_context(ACTOR, 'qubit', workspace_clear=True)

    def _tapestation(self):
        if self.flow.state['network'].get('tapestation_recovery_required'):
            raise TaskError('An unresolved TapeStation request after resume requires controlled abort and retrieval observations')
        definition = self.flow.state['definition']; source = definition['execution']['qc']
        qc = self.flow.state['process']['qc']
        if qc['readiness'] is None:
            self._act('advance_time', seconds=source['parameters']['buffer_equilibration_s'])
            self._act('confirm_tapestation_ready', observations={**{k: True for k in source['required_checks']},
                'buffer_equilibration_s': source['parameters']['buffer_equilibration_s']}, reason=REASON)
        for role in ('ladder', 'sample'):
            if role in self.flow.state['process']['qc']['preparations']: continue
            intent = self.flow.run_id + '.QC.' + role
            self._act('begin_qc_preparation', role=role, intent_id=intent)
            duration = source['parameters']['mix_duration_s'] + source['parameters']['spin_duration_s']
            self._act('advance_time', seconds=duration)
            self._act('confirm_qc_preparation', intent_id=intent, actual_inputs=actual_inputs(self.flow.state, intent),
                actual_outputs=source[role]['effect']['fixture_actual_outputs'], observations={'capped': True, 'mixed': True,
                    'spun_down': True, 'mix_duration_s': source['parameters']['mix_duration_s'],
                    'mix_rpm': source['parameters']['mix_rpm'], 'spin_duration_s': source['parameters']['spin_duration_s']}, reason=REASON)
        qc = self.flow.state['process']['qc']
        if qc['request'] is None:
            run = self.flow.run_id
            self._act('begin_tapestation', instrument_run_id=run+'.TS.Run', analysis_id=run+'.TS.Analysis',
                measurement_id=run+'.TS.Measurement', screen_tape_id=source['screen_tape_id'],
                lane_id=source['sample']['lane_id'], ladder_lane_id=source['ladder']['lane_id'])
        if self.flow.state['process']['qc']['loaded'] is None:
            self._act('confirm_tapestation_loaded', observations={**self.flow.expected_tapestation_loading(),
                'sample_loaded': True, 'ladder_loaded': True, 'identities_confirmed': True}, reason=REASON)
        qc = self.flow.state['process']['qc']
        if qc['run_complete'] is None:
            expected = qc['request']['expected']
            self._act('confirm_tapestation_run_complete', observations={'run_complete': True, 'ladder_accepted': True,
                'instrument_run_id': expected['instrument_run_id'], 'analysis_id': expected['analysis_id']}, reason=REASON)
        if not self.flow.state['imports']:
            artifact = synthetic_report(self.flow.expected_tapestation(), din=8, fragment_size_bp=30000)
            self.flow.act('import_results', ACTOR, artifact=artifact, file_name='synthetic-tapestation.json', origin='synthetic_export')
        if self.flow.state['process']['qc']['review'] is None:
            accepted = [key for key, value in self.flow.state['imports'].items() if value['status'] == 'accepted']
            if len(accepted) != 1: raise TaskError('One accepted TapeStation result is required')
            self._act('review_tapestation', decision='accept', artifact_sha256=accepted[0], reason=REASON)
        for identity, material in self.flow.state['inventory']['materials'].items():
            if material['disposition'] in {'consumed', 'discarded'}: continue
            desired = 'retained' if material['kind'] in {'product', 'reagent'} else 'discarded'
            if material['disposition'] != desired:
                self._act('set_disposition', material_id=identity, disposition=desired, reason=REASON)
        self._act('confirm_inventory', observations=self.flow.inventory_observations())
        self._act('release', workspace_clear=True)
