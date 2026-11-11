"""Persisted B0 vessel tasks: a worker claim never updates custody or volume."""
import copy
import json
import uuid

from manual_tasks import TaskError, encoded, digest
from manual_workflow import ObservationError, ROOT
from dna_quantification_tasks import load_contract, decode_goal, decode_claim, goal_fingerprint
from dna_quantification_stages import build_adapter


def endpoint(goal, side):
    if goal[side + '_kind'] == 'agent':
        return {'kind': 'agent', 'agent_id': goal[side + '_agent_id']}
    return {'kind': 'rack', 'rack_id': goal[side + '_rack_id'], 'place_id': goal[side + '_place_id']}


def interface_generated():
    package = ROOT / 'ros2_ws/src/solidcraftbot_dna_interfaces'
    try:
        report = json.loads((package / 'transport-contract.json').read_text())
        return (report['source_sha256'] == load_contract()['source_sha256']
            and report['generator_sha256'] == digest((ROOT / 'scripts/build_dna_ros_interfaces.py').read_bytes())
            and report['decoder_sha256'] == digest((ROOT / 'scripts/dna_quantification_tasks.py').read_bytes())
            and all(digest((package / name).read_bytes()) == checksum for name, checksum in report['artifacts'].items()))
    except (OSError, ValueError, KeyError, TypeError):
        return False


class TaskPort:
    def task_goal(self, context_id, target, agent_id, goal_id=None):
        state = self.state
        context = state['contexts'][context_id]
        vessel = state['inventory']['vessels'][context['source_vessel_id']]
        sources = {**state['definition']['source_files_sha256'],
                   **state.get('control', {}).get('source_files_sha256', {})}
        task = load_contract()
        goal = {'request_id': (self.command_context['request_id'] if self.command_context else self.run_id + '.local'),
            'goal_id': goal_id or uuid.uuid4().hex, 'run_id': self.run_id,
            'attempt_id': context['attempt_id'], 'context_id': context_id,
            'operation': 'transfer_vessel', 'mode': 'synthetic_only',
            'sample_id': context['sample_id'], 'vessel_id': vessel['id'],
            'executing_agent_id': agent_id, 'source_manifest_sha256': digest(encoded(sources).encode()),
            'task_contract_sha256': task['source_sha256'], 'content_revision': vessel['content_revision']}
        for side, location in [('source', vessel['location']), ('target', target)]:
            goal.update({side + '_kind': location['kind'], side + '_rack_id': location.get('rack_id', ''),
                side + '_place_id': location.get('place_id', ''), side + '_agent_id': location.get('agent_id', '')})
        return decode_goal(goal, task)

    def _validate_goal_binding(self, state, goal):
        context = state['contexts'].get(goal['context_id'])
        if (goal['run_id'] != self.run_id or state['active_context_id'] != goal['context_id']
                or not context or context['attempt_id'] != goal['attempt_id']
                or context['sample_id'] != goal['sample_id']
                or context['source_vessel_id'] != goal['vessel_id']):
            raise TaskError('Task is not bound to the active root/device attempt')
        vessel = state['inventory']['vessels'][goal['vessel_id']]
        sources = {**state['definition']['source_files_sha256'],
                   **state.get('control', {}).get('source_files_sha256', {})}
        if (goal['source_manifest_sha256'] != digest(encoded(sources).encode())
                or vessel['content_revision'] != goal['content_revision']):
            raise TaskError('Stale task sources or vessel-content revision')
        if vessel['location'] != endpoint(goal, 'source'):
            raise ObservationError('Task source does not match the canonical custody observation')
        destination = endpoint(goal, 'target')
        if destination['kind'] == 'rack' and destination != vessel['home']:
            raise TaskError('B0 returns each original/dilution to its declared home rack place')

    def intend_task(self, actor_id, goal):
        goal = decode_goal(goal); checksum = goal_fingerprint(goal)
        existing = self.state.get('task_port', {}).get('goals', {}).get(goal['goal_id'])
        if existing:
            if existing['fingerprint'] != checksum: raise TaskError('Goal id has different task arguments')
            return self.state
        def update(state):
            expected_request = self.command_context['request_id'] if self.command_context else self.run_id + '.local'
            if goal['request_id'] != expected_request:
                raise TaskError('Task request identity does not match the dispatching root command')
            self._validate_goal_binding(state, goal)
            port = state.setdefault('task_port', {'goals': {}, 'pending_goal_id': None})
            if port['pending_goal_id']: raise TaskError('Resolve the pending worker goal first')
            port['goals'][goal['goal_id']] = {'goal': goal, 'fingerprint': checksum,
                'status': 'intended', 'claim': None, 'worker_boot_id': None,
                'root_observation': None}
            port['pending_goal_id'] = goal['goal_id']
            state['executing_agent_id'] = goal['executing_agent_id']
        return self._transition('task.intended', actor_id, update, {'goal': goal})

    def dispatch_task(self, actor_id, goal_id, worker):
        state = self.state
        record = state.get('task_port', {}).get('goals', {}).get(goal_id)
        if not record: raise TaskError('Persist the task intent before dispatch')
        if record['status'] == 'claimed': return copy.deepcopy(record['claim'])
        if record['status'] != 'intended': raise TaskError('Uncertain/retired task must never be redispatched')
        goal = record['goal']
        if worker.agent_id != goal['executing_agent_id']: raise TaskError('Wrong assigned task worker')
        def dispatched(current):
            self._validate_goal_binding(current, goal)
            item = current['task_port']['goals'][goal_id]
            item.update(status='dispatched', worker_boot_id=worker.boot_id)
        self._transition('task.dispatched', actor_id, dispatched, {'goal_id': goal_id})
        # The durable dispatched state is deliberately ambiguous after a crash.
        # A new worker must not use its empty cache to repeat this task.
        try:
            claim = worker.dispatch(goal)
        except BaseException:
            self.mark_task_uncertain(actor_id, goal_id, 'worker_failure')
            raise
        return self.record_task_claim(actor_id, goal_id, claim)

    def record_task_claim(self, actor_id, goal_id, claim):
        record = self.state['task_port']['goals'][goal_id]
        claim = decode_claim(claim, record['goal'])
        if record['status'] == 'claimed':
            if claim != record['claim']: raise TaskError('Conflicting worker claim')
            return copy.deepcopy(claim)
        def update(state):
            item = state['task_port']['goals'][goal_id]
            if (item['status'] != 'dispatched' or item['worker_boot_id'] != claim['worker_boot_id']):
                raise TaskError('Late, restarted or cancelled worker claim is not an observation')
            item.update(status='claimed', claim=copy.deepcopy(claim))
        self._transition('task.claimed', actor_id, update, {'goal_id': goal_id, 'claim': claim})
        return claim

    def mark_task_uncertain(self, actor_id, goal_id, reason):
        def update(state):
            record = state['task_port']['goals'][goal_id]
            record.update(status='uncertain', uncertainty_reason=reason)
            state['status'] = 'cancelling' if state['cancel_requested'] else 'held'
            state['recovery_required'] = 'task_outcome_unknown'
        return self._transition('task.uncertain', actor_id, update,
            {'goal_id': goal_id, 'reason': reason}, allow_held=True)

    def cancel_task(self, actor_id, goal_id):
        def update(state):
            record = state['task_port']['goals'][goal_id]
            if record['status'] == 'observed': raise TaskError('Task observation is already committed')
            record['status'] = 'cancel_requested'
            state['status'] = 'cancelling' if state['cancel_requested'] else 'held'
            state['recovery_required'] = 'task_cancel_requires_observation'
        return self._transition('task.cancel_requested', actor_id, update,
            {'goal_id': goal_id}, allow_held=True)

    def observe_task(self, actor_id, goal_id, observation, evidence='synthetic_person_input'):
        if evidence not in {'synthetic_person_input', 'synthetic_backend'}:
            raise TaskError('Worker/network receipt is not a custody observation')
        before = self.state; record = before['task_port']['goals'][goal_id]
        if record['status'] == 'observed':
            if observation != record['root_observation']: raise TaskError('Conflicting task observation')
            return before
        def update(state):
            item = state['task_port']['goals'][goal_id]; goal = item['goal']
            self._validate_goal_binding(state, goal)
            if item['status'] != 'claimed' or item['claim']['outcome'] != 'claimed_performed':
                raise TaskError('Resolve worker uncertainty through full root inventory reconciliation')
            if (not isinstance(observation, dict) or set(observation) != {'sample_id', 'vessel_id', 'location'}
                    or observation['sample_id'] != goal['sample_id']
                    or observation['vessel_id'] != goal['vessel_id']
                    or observation['location'] != endpoint(goal, 'target')):
                raise ObservationError('Explicit task destination vessel/sample/location observation required')
            adapter = build_adapter(self, state, goal['context_id']); view = adapter.state
            if goal['target_kind'] == 'agent':
                adapter._take(view, actor_id, goal['sample_id'], goal['sample_id'],
                              rack_id=goal['source_rack_id'], place_id=goal['source_place_id'])
                state['inventory']['vessels'][goal['vessel_id']]['location'] = endpoint(goal, 'target')
            else:
                adapter._place(view, actor_id, goal['sample_id'], goal['sample_id'],
                               rack_id=goal['target_rack_id'], place_id=goal['target_place_id'])
            item.update(status='observed', root_observation=copy.deepcopy(observation),
                        observation_evidence=evidence)
            state['task_port']['pending_goal_id'] = None
        return self._transition('task.observed', actor_id, update,
            {'goal_id': goal_id, 'observation': observation, 'observation_evidence': evidence})
