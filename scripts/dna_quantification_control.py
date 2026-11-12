"""Root-journal control binding; receipts never own a second sample ledger."""
import copy
import time

from manual_tasks import TaskError

EVIDENCE = {'synthetic_backend', 'synthetic_person_input', 'network_receipt', 'worker_claim'}


class ExecutionInterrupted(TaskError):
    pass


class NetworkControl:
    """Trusted server context, deliberately absent from the local CLI surface."""
    def _check_control(self, state, check_guard=True):
        binding = state.get('control')
        if not binding:
            return
        context = getattr(self, 'command_context', None)
        if (binding.get('mode') != 'sila2_network/1' or not context
                or context.get('server_uuid') != binding['server_uuid']):
            raise TaskError('Network-bound DNA run: use its SiLA server; CLI is read-only')
        if (state['network']['boot_id'] != context['boot_id']
                and context['command'] != 'ResumeRun'):
            raise TaskError('Stale DNA server boot; explicit ResumeRun required')
        guard = getattr(self, 'transition_guard', None)
        if guard and check_guard:
            guard()

    def _decorate(self, state, payload=None, sequence=None, evidence=None):
        context = getattr(self, 'command_context', None)
        result = dict(payload or {})
        # System fields are deliberately written last. An observation document
        # or a future adapter cannot impersonate another principal/evidence kind.
        result.update(actor_id=state.get('actor_id'), evidence='synthetic_input')
        if not state.get('control'):
            return result
        selected = evidence or context.get('evidence', 'synthetic_backend')
        self._check_control(state, check_guard=selected != 'network_receipt')
        if selected not in EVIDENCE:
            raise TaskError('Unsupported DNA evidence kind')
        now = context['clock']()
        record = state['network']['commands'].get(context['request_id'])
        if record is None:
            record = {key: copy.deepcopy(context[key]) for key in [
                'request_id', 'fingerprint', 'command', 'arguments', 'principal',
                'server_uuid', 'boot_id', 'execution_uuid', 'transport']}
            record.update(status='accepted', accepted_server_time_s=now,
                          confirmation_event_sequence=sequence, response=None)
            state['network']['commands'][context['request_id']] = record
        elif (record['fingerprint'] != context['fingerprint']
              or record['principal'] != context['principal']):
            raise TaskError('Request identifier was already used with different arguments/principal')
        state['network']['boot_id'] = context['boot_id']
        state['network']['last_server_time_s'] = now
        result.update(principal=context['principal'], request_id=context['request_id'],
                      execution_uuid=context['execution_uuid'], server_uuid=context['server_uuid'],
                      boot_id=context['boot_id'], server_time_s=now,
                      evidence=selected, transport=context['transport'],
                      responsible_person_id=state.get('responsible_person_id', state.get('actor_id')),
                      executing_agent_id=state.get('executing_agent_id'))
        return result

    def control_event(self, kind, actor_id, update=lambda state: None, payload=None,
                      evidence='network_receipt'):
        """CAS-only transport metadata transition, also after physical completion."""
        before, revision = self.journal.get_current(self.run_id)
        self._source_check(before)
        self._check_control(before, check_guard=False)
        state = copy.deepcopy(before)
        update(state)
        decorated = self._decorate(state, payload, revision + 1, evidence)
        self.journal.append(self.run_id, revision, kind, decorated, state)
        return state

    def finish_command(self, actor_id, response, outcome='completed', error=None):
        def update(state):
            record = state['network']['commands'].get(self.command_context['request_id'])
            if record is None:
                # A command with no earlier domain effect still has one durable
                # completion; no receipt exists outside this atomic root event.
                self._decorate(state)
                record = state['network']['commands'][self.command_context['request_id']]
            record.update(status=outcome, response=copy.deepcopy(response), error=error,
                          completed_server_time_s=self.command_context['clock']())
        return self.control_event('command_finished', actor_id, update,
            {'command': self.command_context['command'], 'outcome': outcome,
             'status': outcome, 'error': error})

    def resume_network(self, actor_id):
        def update(state):
            previous_boot = state['network']['boot_id']
            for record in state['network']['commands'].values():
                if record['status'] == 'accepted' and record['boot_id'] != self.command_context['boot_id']:
                    record.update(status='uncertain', error='ReconciliationRequired')
            state['session'] = self.session
            if state['status'] not in {'completed', 'cancelled'}:
                state['status'] = 'cancelling' if state['cancel_requested'] else 'held'
                state['recovery_required'] = state['recovery_required'] or 'restart_reconciliation'
            state['network']['previous_boot_id'] = previous_boot
            goal_id = state.get('task_port', {}).get('pending_goal_id')
            if goal_id:
                state['task_port']['goals'][goal_id]['status'] = 'uncertain'
        return self.control_event('session_reopened', actor_id, update,
                                  {'reason': 'explicit_network_resume'})
