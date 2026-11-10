"""Device operations on explicit shared-root and isolated-stage contexts."""
import copy

from manual_tasks import TaskError
from manual_workflow import ObservationError
from nanodrop_manual import NanoDropOperations
from qubit_manual import QubitOperations
from lab_workflow_ledger import StageState, confirm_withdrawal


class StageAdapter:
    EVENT_CLOCK = True
    DEADLINE_FIELD = 'deadline_s'

    def __init__(self, flow, root, stage_id):
        self.flow, self.root, self.stage_id = flow, root, stage_id
        self.journal = flow.journal
        self.run_id = root['run_id'] + '.' + stage_id
        self.state = StageState(root, stage_id)

    def _now(self, state):
        return self.root['logical_time_s']

    def _consume(self, state, sample_id, volume_ul, deviation_reason=None):
        pending = self._pending(state)
        if not pending:
            raise TaskError('A persisted consumption intent is required')
        confirm_withdrawal(self.root, self.stage_id, pending, sample_id, volume_ul, deviation_reason)

    @staticmethod
    def _finish_lifecycle(state, status):
        # Stage completion never releases the root's rack or vessel reservations.
        state.local.update(status=status, workspace_clear=True, session=None)


class NanoDropStage(StageAdapter, NanoDropOperations):
    @staticmethod
    def _pending(state):
        return state['pending_measurement']


class QubitStage(StageAdapter, QubitOperations):
    def _begin_measurement(self, state, actor_id, preparation_id, measurement_id,
                           observed_vessel_id, calibration_id=None):
        vessel=state['derived_vessels'].get(observed_vessel_id)
        holders=[{'kind':'logical','holder_id':p['holder_id'],'place_id':p['place_id']}
                 for p in self.root['definition']['qubit_places'] if p['role']=='holder_slot']
        if not vessel or vessel['location'] not in holders:
            raise TaskError('Observe the prepared tube at a holder before measuring')
        super()._begin_measurement(state,actor_id,preparation_id,measurement_id,observed_vessel_id,calibration_id)
        state['pending_operation']['return_place']=copy.deepcopy(vessel['location'])

    def _finish_measurement(self, state, intent_id, observed_vessel_id, returned_to_holder):
        pending=self._pending(state)
        if pending and pending['kind']=='measurement' and pending['intent_id']==intent_id:
            vessel=state['derived_vessels'].get(observed_vessel_id)
            if returned_to_holder is True and vessel and vessel['location']!=pending['return_place']:
                raise ObservationError('Returned tube must be observed at the recorded holder, not the chamber')
        super()._finish_measurement(state,intent_id,observed_vessel_id,returned_to_holder)

    def _begin_preparation(self, state, actor_id, kind, target_id, vessel_id,
                           observed_vessel_id, holder_id, place_id, empty_tube_confirmed):
        allowed = [{'holder_id': item['holder_id'], 'place_id': item['place_id']}
                   for item in self.root['definition']['qubit_places'] if item['role'] == 'holder_slot']
        if {'holder_id': holder_id, 'place_id': place_id} not in allowed:
            raise TaskError('A holder slot is required; the measurement chamber is not storage')
        super()._begin_preparation(state, actor_id, kind, target_id, vessel_id,
                                  observed_vessel_id, holder_id, place_id, empty_tube_confirmed)


ADAPTERS = {'nanodrop': NanoDropStage, 'qubit': QubitStage}


def initial_cf01_stage(root_id, attempt_number=1):
    return {'status': 'waiting', 'actor_id': None,
            'attempt_id': root_id + '.cf01.A%02d' % attempt_number,
            'deadline_s': None, 'recovery_required': None, 'view': None,
            'report_artifact_sha256': None, 'pending_command': None,
            'retired_attempts': []}


def initial_stage(root_id, definition, stage_id):
    prefix = root_id + '.' + stage_id
    adapter = ADAPTERS[stage_id]
    state = {'status': 'waiting', 'actor_id': None, 'attempt_id': prefix + '.A01',
             'deadline_s': None, 'rack_ready': False, 'workspace_clear': False,
             'recovery_required': None, 'session': None, 'planned_measurements': {},
             'measurements': {}, 'imports': {}, 'results': {}, 'result_review': None,
             **adapter._initial_extra(prefix, definition)}
    state.pop('derived_vessels', None)
    state.pop('logical_time_s', None)
    if stage_id == 'nanodrop':
        for index, sample in enumerate(definition['profile']['samples'], 1):
            state['planned_measurements'][sample['id']] = prefix + '.A01.M%03d' % index
    return state


class StageHandle:
    """Command port for CLI/demo inputs; state is a fresh read-only projection."""
    def __init__(self, flow, stage_id):
        self.flow, self.stage_id = flow, stage_id

    @property
    def state(self):
        return StageState(self.flow.state, self.stage_id)

    def act(self, command, actor_id, **data):
        if command == 'advance_time':
            return self.flow.advance_time(actor_id, **data)
        return self.flow.stage_act(self.stage_id, command, actor_id, **data)

    def import_content(self, content, actor_id, file_name='synthetic-report.csv'):
        return self.flow.stage_act(self.stage_id, 'import_results', actor_id,
                                   artifact=content, file_name=file_name, origin='synthetic_export')
