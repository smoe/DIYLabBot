"""Atomic SiLA receipts on the existing test-only S09 material Root.

Transport identity stays in a nested receipt. It never changes the fixture
observation, operator attribution, material provenance or the canonical ledger.
"""
import copy
import math
import uuid

import manual_process_clock as process_clock
from cutrun_input_sonication_workflow import InputSonicationWorkflow
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, text

MODE = 's09_sila2_network/1'
CONTEXT_FIELDS = ('request_id', 'fingerprint', 'command', 'arguments', 'principal',
                  'server_uuid', 'boot_id', 'execution_uuid', 'transport')


class ExecutionInterrupted(TaskError):
    """The controller stopped this execution at a Root transition boundary."""


class NetworkInputSonicationWorkflow(InputSonicationWorkflow):
    # A crashed CreateRun can have durably introduced the inventory before its
    # first acceptance. Only the network adapter may explicitly recover it;
    # the canonical handler still enforces created state and initial places.
    RECOVERY_COMMANDS = InputSonicationWorkflow.RECOVERY_COMMANDS | {'accept_inventory'}

    def __init__(self, journal, run_id, session=None, *, clock=None,
                 command_context=None, transition_guard=None):
        self.command_context = command_context
        self.transition_guard = transition_guard
        super().__init__(journal, run_id, session, clock=clock)

    @staticmethod
    def _validate_context(context):
        if not isinstance(context, dict) or not set(CONTEXT_FIELDS) <= set(context):
            raise TaskError('Complete S09 network command context required')
        for key in CONTEXT_FIELDS:
            if key != 'arguments':
                text(context[key], 'S09 command ' + key)
        if not isinstance(context['arguments'], dict) or not callable(context.get('clock')):
            raise TaskError('S09 command arguments and server clock required')
        try:
            fingerprint = digest(encoded({'command': context['command'],
                                          'arguments': context['arguments']}).encode())
        except (TypeError, ValueError) as error:
            raise TaskError('Finite JSON command arguments required') from error
        if context['fingerprint'] != fingerprint:
            raise TaskError('S09 command fingerprint does not match its arguments')
        if context['arguments'].get('request_identifier') != context['request_id']:
            raise TaskError('S09 request identity does not match its command arguments')

    @staticmethod
    def _verify_control(control):
        if (not isinstance(control, dict) or control.get('mode') != MODE
                or not isinstance(control.get('source_files_sha256'), dict)
                or not control['source_files_sha256']):
            raise TaskError('Explicit S09 network binding and source pins required')
        text(control.get('server_uuid'), 'S09 server identity')
        for name, checksum in control['source_files_sha256'].items():
            if not isinstance(name, str):
                raise TaskError('S09 network source path required')
            path = (ROOT / name).resolve()
            if (not path.is_relative_to(ROOT) or not path.is_file()
                    or digest(path.read_bytes()) != checksum):
                raise TaskError('S09 network source changed; inspect the pinned run: ' + name)

    @classmethod
    def _check_context(cls, state, context, guard=None, *, allow_resume=False):
        cls._verify_control(state.get('control'))
        cls._validate_context(context)
        if context['arguments'].get('run_identifier') != state['run_id']:
            raise TaskError('S09 command arguments identify another Root run')
        if context['server_uuid'] != state['control']['server_uuid']:
            raise TaskError('S09 run is bound to another SiLA server')
        if (state['network']['boot_id'] != context['boot_id']
                and not (allow_resume and context['command'] == 'ResumeRun')):
            raise TaskError('Stale S09 server boot; explicit ResumeRun required')
        previous = state['network']['commands'].get(context['request_id'])
        if previous is not None:
            if any(previous[key] != context[key] for key in CONTEXT_FIELDS):
                raise TaskError('Request identifier was already used with different command context')
            if previous['status'] != 'accepted':
                raise TaskError('S09 network command was already finished; return its stored receipt')
        if guard is not None:
            guard()

    def _check_network_control(self, state, *, check_guard=True, check_session=True):
        self._check_context(state, self.command_context,
                            self.transition_guard if check_guard else None)
        if check_session and (self.session != state['session']
                or self.session is None and state['status'] not in {'completed', 'cancelled'}):
            raise TaskError('Stale S09 network session; explicit ResumeRun required')

    @classmethod
    def _receipt(cls, state, context, sequence):
        now = context['clock']()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise TaskError('Finite S09 server time required')
        record = state['network']['commands'].get(context['request_id'])
        if record is None:
            record = {key: copy.deepcopy(context[key]) for key in CONTEXT_FIELDS}
            record.update(status='accepted', accepted_server_time_s=now,
                          confirmation_event_sequence=sequence, response=None)
            state['network']['commands'][context['request_id']] = record
        state['network']['boot_id'] = context['boot_id']
        state['network']['last_server_time_s'] = now
        return {key: copy.deepcopy(context[key]) for key in CONTEXT_FIELDS if key != 'arguments'} | {
            'evidence': 'network_receipt', 'server_time_s': now,
            'responsible_person_id': state.get('responsible_person_id'),
            'executing_agent_id': state.get('executing_agent_id')}

    @classmethod
    def _prepare_create_state(cls, state, creation_context):
        if not isinstance(creation_context, dict):
            raise TaskError('Create new S09 network runs through their SiLA server')
        control, context = creation_context['control'], creation_context['command_context']
        cls._verify_control(control)
        cls._validate_context(context)
        if context['command'] != 'CreateRun' or context['server_uuid'] != control['server_uuid']:
            raise TaskError('Matching S09 CreateRun command and server binding required')
        state['control'] = copy.deepcopy(control)
        state['network'] = {'boot_id': context['boot_id'], 'commands': {}}
        cls._check_context(state, context, creation_context['transition_guard'])
        state['creation_receipt'] = {'network_receipt': cls._receipt(state, context, 1)}

    @classmethod
    def create(cls, journal, source=None, *, materials, vessels, reactions, actors,
               run_id=None, clock=None, original_pdf=None, evidence_files=None,
               control=None, command_context=None, transition_guard=None):
        flow = super().create(journal, source, materials=materials, vessels=vessels,
            reactions=reactions, actors=actors, run_id=run_id, clock=clock,
            original_pdf=original_pdf, evidence_files=evidence_files,
            _creation_context={'control': control, 'command_context': command_context,
                               'transition_guard': transition_guard})
        flow.command_context, flow.transition_guard = command_context, transition_guard
        return flow

    @classmethod
    def open(cls, journal, run_id, resume=False, *, clock=None, clock_mode=None,
             control=None, command_context=None, transition_guard=None):
        state, revision = journal.state(run_id)
        cls._validate_format(state)
        cls._clock_matches(journal, state, clock_mode)
        cls._verify_runtime(state)
        cls._verify_initial_artifacts(journal, state)
        if control is not None and control != state.get('control'):
            raise TaskError('Existing S09 network binding cannot be changed or migrated')
        cls._check_context(state, command_context, transition_guard, allow_resume=True)
        if command_context['command'] != 'ResumeRun':
            raise TaskError('Explicit ResumeRun command required to reopen S09')
        if command_context['request_id'] in state['network']['commands']:
            raise TaskError('ResumeRun was already accepted; return its stored receipt')
        if state['session'] is not None and not resume:
            raise TaskError('Explicit resume required for the previous S09 network session')
        if clock is None:
            raise TaskError('Explicit test clock required for S09 network resume')
        sample = process_clock.validate_sample(clock.sample())
        if sample['source_kind'] != state['definition']['clock_source_kind']:
            raise TaskError('Clock source kind cannot switch between real and test clocks')
        previous_boot = state['network']['boot_id']
        previous_session = state['session']
        for record in state['network']['commands'].values():
            if record['status'] == 'accepted':
                record.update(status='uncertain', error='ReconciliationRequired')
        state['clock'] = process_clock.refresh(state['clock'], sample)
        state['logical_time_s'] = state['clock']['lower_s']
        state['session'] = uuid.uuid4().hex
        if state['status'] not in {'completed', 'cancelled'}:
            state['recovery_required'], state['workspace_clear'] = 'manual_session_restarted', False
        state['network'].update(previous_boot_id=previous_boot, previous_session=previous_session)
        receipt = cls._receipt(state, command_context, revision + 1)
        journal.append(run_id, revision, 'manual_session_opened', {
            'explicit_resume': resume, 'recorded_at': sample, 'evidence': 'clock_observation',
            'no_effect_replayed': True, 'network_receipt': receipt}, state)
        return cls(journal, run_id, state['session'], clock=clock,
                   command_context=command_context, transition_guard=transition_guard)

    def _event_evidence(self, state, command, actor_id, data):
        result = super()._event_evidence(state, command, actor_id, data)
        result['network_receipt'] = self._receipt(state, self.command_context,
                                                self.journal.state(self.run_id)[1] + 1)
        return result

    def _before_transition(self, state):
        self._verify_control(state.get('control'))
        super()._before_transition(state)
        # Shared dispatch snapshots this proposal before calling a handler.
        # Rejected observations and deadline events therefore retain the same
        # first receipt as successful effects, in their single Root commit.
        self._receipt(state, self.command_context, self.journal.state(self.run_id)[1] + 1)

    def _deadline_event(self, state):
        payload, deadline_state = super()._deadline_event(state)
        payload['network_receipt'] = self._receipt(deadline_state, self.command_context,
                                                  self.journal.state(self.run_id)[1] + 1)
        return payload, deadline_state

    def control_event(self, kind, update, payload=None, *, trusted=False):
        """Atomic controller bookkeeping; trusted interruptions skip only the lease guard."""
        return self._control_event(kind, update, payload, trusted=trusted)

    def _control_event(self, kind, update, payload=None, *, trusted=False, terminal_finish=False):
        before, revision = self.journal.state(self.run_id)
        self._verify_runtime(before)
        self._verify_initial_artifacts(self.journal, before)
        final_receipt = (terminal_finish and kind == 'command_finished'
                         and before['status'] in {'completed', 'cancelled'} and before['session'] is None)
        self._check_network_control(before, check_guard=not trusted, check_session=not final_receipt)
        if final_receipt:
            # The domain lifecycle closes its session in the terminal commit.
            # Only that execution's correlated completion may follow it. A
            # generic controller event or a stale writer gets no such exception.
            trace = self.journal.history(self.run_id)
            own = before['network']['commands'].get(self.command_context['request_id'])
            receipt = trace[-1]['payload'].get('network_receipt', {})
            if (own is None or own['status'] != 'accepted' or self.session is None or len(trace) < 2
                    or trace[-2]['state']['session'] != self.session
                    or trace[-2]['state']['status'] in {'completed', 'cancelled'}
                    or receipt.get('request_id') != self.command_context['request_id']
                    or receipt.get('execution_uuid') != self.command_context['execution_uuid']):
                raise TaskError('Stale terminal S09 execution cannot finish another command receipt')
        state = copy.deepcopy(before)
        receipt = self._receipt(state, self.command_context, revision + 1)
        update(state)
        if state['control'] != before['control']:
            raise TaskError('S09 network binding is immutable')
        event = {**(payload or {}), 'actor_id': state.get('actor_id'),
                 'evidence': 'network_receipt', 'network_receipt': receipt}
        self.journal.append(self.run_id, revision, kind, event, state)
        return state

    def finish_command(self, response, outcome='completed', error=None):
        text(outcome, 'command completion outcome')
        if outcome == 'accepted':
            raise TaskError('A completed command cannot remain accepted')
        def finish(state):
            record = state['network']['commands'][self.command_context['request_id']]
            record.update(status=outcome, response=copy.deepcopy(response), error=error,
                          completed_server_time_s=state['network']['last_server_time_s'])
        return self._control_event('command_finished', finish, {
            'command': self.command_context['command'], 'outcome': outcome, 'error': error},
            trusted=True, terminal_finish=True)

    def close(self):
        if self.session is not None:
            self.control_event('session_closed', lambda state: state.update(session=None))
            self.session = None
