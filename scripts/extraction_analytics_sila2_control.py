"""Atomic network receipts on the existing extraction material Root.

The network principal is transport identity. Synthetic actor observations and
material provenance remain separate from authentication, leases and receipts.
"""
import copy
import math
import uuid

from dna_quantification_control import ExecutionInterrupted
from extraction_analytics_workflow import ExtractionAnalyticsWorkflow
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, text

MODE = 'extraction_analytics_sila2_network/1'
CONTEXT_FIELDS = ('request_id', 'fingerprint', 'command', 'arguments', 'principal',
                  'server_uuid', 'boot_id', 'execution_uuid', 'transport')


class NetworkExtractionAnalyticsWorkflow(ExtractionAnalyticsWorkflow):
    RECOVERY_COMMANDS = ExtractionAnalyticsWorkflow.RECOVERY_COMMANDS | {'accept_inventory'}

    def __init__(self, journal, run_id, session=None, *, command_context=None, transition_guard=None):
        self.command_context, self.transition_guard = command_context, transition_guard
        super().__init__(journal, run_id, session)

    @property
    def state(self):
        state, _ = self.journal.get_current(self.run_id)
        self._validate_format(state)
        return state

    @staticmethod
    def _validate_context(context):
        if not isinstance(context, dict) or not set(CONTEXT_FIELDS) <= set(context):
            raise TaskError('Complete extraction network command context required')
        for key in CONTEXT_FIELDS:
            if key != 'arguments': text(context[key], 'network ' + key)
        if not isinstance(context['arguments'], dict) or not callable(context.get('clock')):
            raise TaskError('Network arguments and server clock required')
        fingerprint = digest(encoded({'command': context['command'], 'arguments': context['arguments']}).encode())
        if context['fingerprint'] != fingerprint or context['arguments'].get('request_identifier') != context['request_id']:
            raise TaskError('Network fingerprint/request differs from normalized arguments')

    @staticmethod
    def _verify_control(control):
        if not isinstance(control, dict) or control.get('mode') != MODE or not control.get('source_files_sha256'):
            raise TaskError('Explicit extraction network binding and source pins required')
        text(control.get('server_uuid'), 'network server identity')
        if not isinstance(control['source_files_sha256'], dict): raise TaskError('Network source manifest required')
        for name, expected in control['source_files_sha256'].items():
            if not isinstance(name, str): raise TaskError('Network source path required')
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file() or digest(path.read_bytes()) != expected:
                raise TaskError('Extraction network source changed; inspect pinned run: ' + name)

    @classmethod
    def _check_context(cls, state, context, guard=None, *, allow_resume=False):
        cls._verify_control(state.get('control')); cls._validate_context(context)
        if context['arguments'].get('run_identifier') != state['run_id']:
            raise TaskError('Network command identifies another extraction Root')
        if context['server_uuid'] != state['control']['server_uuid']:
            raise TaskError('Extraction run belongs to another server')
        if state['network']['boot_id'] != context['boot_id'] and not (allow_resume and context['command'] == 'ResumeRun'):
            raise TaskError('Stale extraction server boot; explicit ResumeRun required')
        previous = state['network']['commands'].get(context['request_id'])
        if previous is not None:
            if any(previous[key] != context[key] for key in CONTEXT_FIELDS):
                raise TaskError('Request identifier was reused with different command context')
            if previous['status'] != 'accepted':
                raise TaskError('Command already finished; return its stored receipt without redispatch')
        if guard is not None: guard()

    def _check_network_control(self, state, *, check_guard=True, check_session=True):
        self._check_context(state, self.command_context, self.transition_guard if check_guard else None)
        if check_session and (self.session != state['session'] or self.session is None and state['status'] not in {'completed', 'cancelled'}):
            raise TaskError('Stale extraction network session; explicit ResumeRun required')

    @classmethod
    def _receipt(cls, state, context, sequence):
        now = context['clock']()
        if type(now) not in (int, float) or not math.isfinite(now): raise TaskError('Finite server time required')
        record = state['network']['commands'].get(context['request_id'])
        if record is None:
            record = {key: copy.deepcopy(context[key]) for key in CONTEXT_FIELDS}
            record.update(status='accepted', accepted_server_time_s=now,
                          confirmation_event_sequence=sequence, response=None)
            state['network']['commands'][context['request_id']] = record
        state['network']['boot_id'], state['network']['last_server_time_s'] = context['boot_id'], now
        return {key: copy.deepcopy(context[key]) for key in CONTEXT_FIELDS if key != 'arguments'} | {
            'evidence': 'network_receipt', 'server_time_s': now,
            'responsible_person_id': state.get('responsible_person_id'), 'executing_agent_id': None}

    @classmethod
    def _prepare_create_state(cls, state, creation_context):
        if not isinstance(creation_context, dict) or set(creation_context) != {'control', 'command_context', 'transition_guard', 'actor_id'}:
            raise TaskError('Create bound extraction runs through the SiLA service')
        super()._prepare_create_state(state, None)
        control, context = creation_context['control'], creation_context['command_context']
        cls._verify_control(control); cls._validate_context(context)
        if context['command'] != 'CreateRun' or context['server_uuid'] != control['server_uuid']:
            raise TaskError('Matching CreateRun command and extraction server required')
        if context['arguments'].get('family_identifier') != state['definition']['execution']['analytics']['family']:
            raise TaskError('CreateRun receipt family differs from its extraction recipe')
        state['control'] = copy.deepcopy(control)
        state['network'] = {'boot_id': context['boot_id'], 'commands': {}}
        state['responsible_person_id'] = text(creation_context['actor_id'], 'synthetic responsible actor')
        cls._check_context(state, context, creation_context['transition_guard'])
        state['creation_receipt'] = {'network_receipt': cls._receipt(state, context, 1)}

    @classmethod
    def create(cls, journal, source=None, run_id=None, *, control=None, command_context=None,
               transition_guard=None, actor_id='SYN.ExtractionAnalytics.Operator'):
        flow = super().create(journal, source, run_id, _creation_context={
            'control': control, 'command_context': command_context,
            'transition_guard': transition_guard, 'actor_id': actor_id})
        flow.command_context, flow.transition_guard = command_context, transition_guard
        return flow

    @classmethod
    def open(cls, journal, run_id, resume=False, clock_mode=None, *, control=None,
             command_context=None, transition_guard=None):
        state, revision = journal.state(run_id)
        cls._validate_format(state); cls._clock_matches(journal, state, clock_mode)
        cls._verify_sources(state)
        if control is not None and control != state.get('control'): raise TaskError('Network binding cannot be migrated')
        cls._check_context(state, command_context, transition_guard, allow_resume=True)
        if command_context['command'] != 'ResumeRun' or command_context['request_id'] in state['network']['commands']:
            raise TaskError('A new explicit ResumeRun command is required')
        if not resume: raise TaskError('Explicit resume=true required')
        previous_boot, previous_session = state['network']['boot_id'], state['session']
        for record in state['network']['commands'].values():
            if record['status'] == 'accepted': record.update(status='uncertain', error='ReconciliationRequired')
        state['session'] = uuid.uuid4().hex
        if state['status'] not in {'completed', 'cancelled'}:
            state['recovery_required'], state['workspace_clear'] = 'network_session_restarted', False
        state['network'].update(previous_boot_id=previous_boot, previous_session=previous_session)
        if state['process']['qc']['request'] is not None and state['process']['qc']['run_complete'] is None:
            state['network']['tapestation_recovery_required'] = True
        receipt = cls._receipt(state, command_context, revision + 1)
        if transition_guard: transition_guard()
        journal.append(run_id, revision, 'network_session_opened', {'explicit_resume': True,
            'no_effect_replayed': True, 'evidence': 'network_receipt', 'network_receipt': receipt}, state)
        return cls(journal, run_id, state['session'], command_context=command_context, transition_guard=transition_guard)

    def _before_transition(self, state):
        super()._before_transition(state)
        self._receipt(state, self.command_context, self.journal.get_current(self.run_id)[1] + 1)

    def _event_evidence(self, state, command, actor_id, data):
        return {**super()._event_evidence(state, command, actor_id, data),
            'network_receipt': self._receipt(state, self.command_context, self.journal.get_current(self.run_id)[1] + 1)}

    def _after_transition(self, state, command, actor_id, data, *, rejected=False):
        super()._after_transition(state, command, actor_id, data, rejected=rejected)
        self._check_network_control(state, check_session=state['status'] not in {'completed', 'cancelled'})

    def _deadline_event(self, state):
        self._check_network_control(state)
        payload, proposal = super()._deadline_event(state)
        payload['network_receipt'] = self._receipt(proposal, self.command_context, self.journal.get_current(self.run_id)[1] + 1)
        return payload, proposal

    def control_event(self, kind, update, payload=None, *, trusted=False, terminal_finish=False):
        before, revision = self.journal.get_current(self.run_id)
        self._verify_sources(before)
        final = terminal_finish and kind == 'command_finished' and before['status'] in {'completed', 'cancelled'} and before['session'] is None
        self._check_network_control(before, check_guard=not trusted, check_session=not final)
        if final:
            trace = self.journal.history(self.run_id)
            receipt = trace[-1]['payload'].get('network_receipt', {})
            if (self.session is None or len(trace) < 2 or trace[-2]['state']['session'] != self.session
                    or trace[-2]['state']['status'] in {'completed', 'cancelled'}
                    or receipt.get('request_id') != self.command_context['request_id']
                    or receipt.get('execution_uuid') != self.command_context['execution_uuid']):
                raise TaskError('Stale terminal extraction execution cannot finish another receipt')
        state = copy.deepcopy(before)
        receipt = self._receipt(state, self.command_context, revision + 1)
        update(state)
        if state['control'] != before['control']: raise TaskError('Network binding is immutable')
        event = {**(payload or {}), 'actor_id': state.get('actor_id'), 'evidence': 'network_receipt', 'network_receipt': receipt}
        if not trusted and self.transition_guard: self.transition_guard()
        self.journal.append(self.run_id, revision, kind, event, state)
        return state

    def finish_command(self, response, outcome='completed', error=None):
        if outcome not in {'completed', 'failed', 'interrupted'}: raise TaskError('Explicit terminal command outcome required')
        def finish(state):
            record = state['network']['commands'][self.command_context['request_id']]
            record.update(status=outcome, response=copy.deepcopy(response), error=error,
                          completed_server_time_s=state['network']['last_server_time_s'])
            if state['status'] in {'completed', 'cancelled'}:
                state['session'] = None
        return self.control_event('command_finished', finish,
            {'command': self.command_context['command'], 'outcome': outcome, 'error': error}, trusted=True, terminal_finish=True)

    def close(self):
        if self.session is not None:
            self.control_event('session_closed', lambda state: state.update(session=None))
            self.session = None

    def act(self, command, actor_id, artifact=None, **data):
        result = super().act(command, actor_id, artifact=artifact, **data)
        callback = getattr(self, 'checkpoint_callback', None)
        if callback is not None: callback(command, data)
        return result
