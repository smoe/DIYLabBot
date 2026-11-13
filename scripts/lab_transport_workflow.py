"""Opt-in T2 rack transport in the existing synthetic laboratory owner.

The queue owns no inventory or quantities. Both transport and instrument
operations commit through the same journal root and revision CAS.
"""
import copy
import re
import uuid

import async_transport_domain as transport
from async_transport import verify_sources
from lab_workflow import Workflow, TERMINAL
from lab_workflow_ledger import manifest_samples, original_location
from lab_transport_sources import SOURCE, load
from manual_tasks import TaskError, digest, encoded

FORMAT = 'solidcraftbot.synthetic-lab-transport-state/2'
DEFINITION_FORMAT = 'solidcraftbot.synthetic-lab-transport-workflow/2'
RUNTIME = ['scripts/lab_workflow.py', 'scripts/lab_workflow_ledger.py',
           'scripts/lab_workflow_stages.py', 'scripts/run_lab_workflow.py',
           'scripts/lab_transport_workflow.py', 'scripts/async_transport.py']
METADATA = {'nanodrop.import_results', 'nanodrop.review_results',
            'nanodrop.discard_import', 'nanodrop.release'}
RECOVERY = {'reconcile', 'cancel', 'finish_cancel', 'check_deadline'}


class TransportWorkflow(Workflow):
    STATE_FORMAT = FORMAT

    @staticmethod
    def _format(state):
        if (state.get('format') != FORMAT
                or state.get('definition', {}).get('format') != DEFINITION_FORMAT):
            raise TaskError('Explicit T2 laboratory transport workflow required; no implicit migration')
        if (not isinstance(state.get('transport'), dict)
                or not isinstance(state.get('transport_bindings'), dict)
                or type(state.get('transport_admitted')) is not bool):
            raise TaskError('Versioned embedded transport state required')

    @staticmethod
    def _topology(state):
        return state['definition']['transport']['topology']

    @staticmethod
    def _routes(state):
        return {route['id']: route for route in state['definition']['transport']['routes']}

    @staticmethod
    def _manifests(state):
        """An identity view of canonical originals, never another material ledger."""
        rack_id = state['definition']['rack_instance']
        result = []
        for sample_id, sample in manifest_samples(state).items():
            vessel = state['inventory']['vessels'][sample['vessel_id']]
            result.append({'place_id': sample['rack_place_id'], 'vessel_id': sample['vessel_id'],
                           'content_revision': vessel['content_revision'],
                           'materials': [{'material_id': sample_id, 'origin_id': None}]})
        return {rack_id: sorted(result, key=lambda item: (item['place_id'], item['vessel_id']))}

    def transport_manifests(self):
        return copy.deepcopy(self._manifests(self.state))

    @classmethod
    def create(cls, journal, source=SOURCE, run_id=None):
        definition = load(source, runtime_sources=RUNTIME)
        run_id = run_id or 'SYN.LAB.Transport.' + uuid.uuid4().hex[:12]
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise TaskError('Run id requires 1-64 ASCII letters, digits, dots, underscores or hyphens')
        session = uuid.uuid4().hex
        state = cls.initial_state(definition, run_id, session)
        state.update(transport_bindings={}, transport_admitted=False)
        state['transport'] = transport.embedded_initial(cls._topology(state), cls._manifests(state), run_id, session)
        verify_sources(definition)
        journal.create(run_id, state, immutable_definition=True)
        return cls(journal, run_id, session)

    @classmethod
    def open(cls, journal, run_id, resume=False):
        if type(resume) is not bool:
            raise TaskError('Explicit boolean resume required')
        state, revision = journal.get_current(run_id, verify=True)
        cls._format(state)
        verify_sources(state['definition'])
        transport.embedded_audit(state['transport'], cls._topology(state), cls._manifests(state))
        if not resume:
            return cls(journal, run_id)
        previous = copy.deepcopy(state)
        session = uuid.uuid4().hex
        state['session'] = session
        state['transport'] = transport.embedded_apply(
            state['transport'], 'resume', {'session': session},
            cls._topology(state)['owner_principal'], cls._topology(state), cls._manifests(state))
        if state['status'] not in TERMINAL and state['resources']:
            stage = state['stages'][state['active_stage']]
            reason = ('cf01_context_lost' if state['active_stage'] == 'cf01' and stage['status'] != 'ready'
                      else 'session_restarted')
            state['recovery_required'] = state['recovery_required'] or reason
            stage['recovery_required'] = stage['recovery_required'] or reason
            if state['status'] != 'cancelling':
                state['status'] = 'held'
        flow = cls(journal, run_id, session)
        flow._after_transition(previous, state, 'transport.session_resumed')
        journal.append(run_id, revision, 'transport.session_resumed',
                       {'explicit_resume': True, 'evidence': 'synthetic_session_resume'}, state)
        return flow

    def close(self):
        state, revision = self.journal.get_current(self.run_id)
        self._format(state)
        if self.session and state['session'] == self.session:
            verify_sources(state['definition'])
            state['session'] = None
            self.journal.append(self.run_id, revision, 'session_closed', {}, state)
        self.session = None

    def _terminal_transition_allowed(self, kind):
        return kind == 'transport.observe'

    @staticmethod
    def _queue_uncertain(state):
        return any(job['control'] != 'active' or job['phase'] not in transport.TERMINAL
                   for job in state['transport']['jobs'].values())

    @staticmethod
    def _payload_claimed(state):
        rack_id = state['definition']['rack_instance']
        return any(job['rack_id'] == rack_id and (job['claims'] or job['control'] == 'held')
                   for job in state['transport']['jobs'].values())

    @staticmethod
    def _originals_returned(state):
        for sample_id, sample in manifest_samples(state).items():
            vessel = state['inventory']['vessels'][sample['vessel_id']]
            if (vessel['location'] != original_location(state, sample_id)
                    or not vessel['return_confirmation'] or vessel['volume_uncertain']):
                return False
        return not any(record['outcome'] in {'intent', 'unknown'} for record in state['bookings'].values())

    @classmethod
    def _nanodrop_finished_handling(cls, state):
        stage = state['stages']['nanodrop']
        return (stage['pending_measurement'] is None
                and set(stage['measurements']) == set(stage['planned_measurements'].values())
                and cls._originals_returned(state))

    @classmethod
    def _route_ready(cls, state, route):
        if not state['transport_admitted'] or not cls._originals_returned(state):
            raise TaskError('Confirmed complete rack and resolved contents required before transport')
        source = route['source_stage']
        stage = state['stages'][source]
        if stage['recovery_required'] or state['recovery_required']:
            raise TaskError('Reconcile the source stage before transport')
        ready = stage['status'] == 'completed'
        if source == 'nanodrop':
            ready = ready or cls._nanodrop_finished_handling(state)
        if not ready:
            raise TaskError('Source sample handling must finish before transport')
        if state['transport']['rack_placements'][state['definition']['rack_instance']] != {
                'kind': 'endpoint', 'endpoint_id': route['source_endpoint']}:
            raise TaskError('Rack is not confirmed at the route source endpoint')

    @classmethod
    def _inbound_job(cls, state, stage_id):
        routes = [route for route in cls._routes(state).values() if route['target_stage'] == stage_id]
        if not routes:
            return None
        route = routes[0]
        job_id = state['transport_bindings'].get(route['id'])
        job = state['transport']['jobs'].get(job_id)
        return route, job

    @classmethod
    def _receiver_ready(cls, state, stage_id):
        inbound = cls._inbound_job(state, stage_id)
        if inbound is None:
            return True
        route, job = inbound
        if (job is None or job['phase'] != 'completed' or job['control'] != 'active'
                or cls._payload_claimed(state)):
            return False
        if state['stages'][route['source_stage']]['status'] != 'completed':
            return False
        return state['transport']['rack_placements'][state['definition']['rack_instance']] == {
            'kind': 'endpoint', 'endpoint_id': route['target_endpoint']}

    @classmethod
    def _sync_receiver(cls, state):
        stage_id = state['active_stage']
        if stage_id not in {'nanodrop', 'qubit'}:
            return
        stage = state['stages'][stage_id]
        if stage['status'] in {'waiting_transport', 'ready'}:
            ready = cls._receiver_ready(state, stage_id)
            stage.update(status='ready' if ready else 'waiting_transport', rack_ready=ready)
            if state['recovery_required'] is None and state['status'] not in TERMINAL | {'cancelling'}:
                state['status'] = 'running' if ready else 'waiting_transport'

    def _before_transition(self, state, kind):
        verify_sources(state['definition'])
        if kind.startswith('transport.'):
            return
        if kind == 'time_advanced':
            return
        if kind in METADATA and self._nanodrop_finished_handling(state):
            return
        if self._payload_claimed(state):
            raise TaskError('Transport payload claim or historical uncertainty blocks sample operations')
        if kind.startswith(('nanodrop.', 'qubit.')) or kind == 'manual_handover':
            command = kind.split('.', 1)[-1]
            if command not in RECOVERY and not self._receiver_ready(state, state['active_stage']):
                raise TaskError('Confirmed inbound transport and source release required')

    def _after_transition(self, before, state, kind):
        if kind == 'rack_accepted':
            state['transport_admitted'] = True
        if kind == 'cf01.attempt_restarted':
            state['transport'] = transport.embedded_apply(
                state['transport'], 'resume', {'session': state['session']},
                self._topology(state)['owner_principal'], self._topology(state), self._manifests(state))
        if state['status'] in TERMINAL and before['status'] not in TERMINAL:
            # A live inbox can retain late evidence. Restart still needs an
            # explicit resume; device mutations remain terminally forbidden.
            state['session'] = before['session']
        self._sync_receiver(state)
        self._audit_transport_context(state)
        state['resources'] = self._resources(state)
        verify_sources(state['definition'])

    def _audit_transport_context(self, state):
        transport.embedded_audit(state['transport'], self._topology(state), self._manifests(state))
        if state['transport']['run_id'] != state['run_id']:
            raise TaskError('Transport and laboratory owner differ')
        if state['session'] is not None and state['transport']['session'] != state['session']:
            raise TaskError('Owner and transport session differ')
        if set(state['transport_bindings']) - set(self._routes(state)):
            raise TaskError('Unknown route binding')
        if len(set(state['transport_bindings'].values())) != len(state['transport_bindings']):
            raise TaskError('A transport job cannot satisfy two routes')
        for route_id, job_id in state['transport_bindings'].items():
            job = state['transport']['jobs'].get(job_id)
            route = self._routes(state)[route_id]
            if job is None or any(job[field] != route[field] for field in ['source_endpoint', 'target_endpoint', 'agent_id']):
                raise TaskError('Route and job binding differ')
        if set(state['transport']['jobs']) != set(state['transport_bindings'].values()):
            raise TaskError('Transport jobs require an explicit workflow route')

    @staticmethod
    def _resources(state):
        if not state['transport_admitted']:
            return []
        transport_holds = transport.embedded_resources(
            state['transport'], TransportWorkflow._topology(state), TransportWorkflow._manifests(state))
        if state['status'] in TERMINAL:
            return transport_holds
        return sorted(set(Workflow._resources(state)) | set(transport_holds))

    def _next_stage(self, state):
        super()._next_stage(state)
        if state['status'] not in TERMINAL:
            state['stages'][state['active_stage']].update(status='waiting_transport', rack_ready=False)
            self._sync_receiver(state)
            state['resources'] = self._resources(state)

    @staticmethod
    def _execution_ready(state):
        if (not state['transport_admitted'] or state['status'] not in {'running', 'waiting_transport'}
                or state['recovery_required'] or state['logical_time_s'] >= state['deadline_s']):
            raise TaskError('Root hold, cancellation or deadline blocks new transport execution')

    def _transport_transition(self, operation, principal, request_id, args, artifact=None):
        transport.ident(principal); transport.ident(request_id)
        fingerprint = digest(encoded({'operation': operation, 'arguments': args}).encode())
        committed = False
        def update(state):
            nonlocal committed
            queue = state['transport']
            previous = queue['requests'].get(request_id)
            if previous is not None:
                if (previous['principal'] != principal or previous['fingerprint'] != fingerprint
                        or previous['operation'] != operation or previous['arguments'] != args):
                    raise TaskError('Request identity has conflicting arguments or principal')
                return False
            if operation == 'prepare_route':
                transport.exact(args, 'route_id job_id', 'route preparation')
                self._execution_ready(state)
                route_id, job_id = args['route_id'], args['job_id']
                if route_id not in self._routes(state):
                    raise TaskError('Unknown transport route')
                if route_id in state['transport_bindings']:
                    raise TaskError('Route already has a transport job; no implicit retry')
                route = self._routes(state)[route_id]
                self._route_ready(state, route)
                for command, data in [
                    ('request', {'job_id': job_id, 'rack_id': state['definition']['rack_instance'],
                                 'target_endpoint': route['target_endpoint'], 'agent_id': route['agent_id']}),
                    ('reserve', {'job_id': job_id}), ('prepare', {'job_id': job_id})]:
                    queue = transport.embedded_apply(queue, command, data, principal,
                                                     self._topology(state), self._manifests(state))
                state['transport_bindings'][route_id] = job_id
            else:
                if operation not in {'observe', 'worker_claim', 'hold', 'cancel', 'reconcile', 'mark_dispatched'}:
                    raise TaskError('Use prepare_transport or explicit session resume for this operation')
                if args.get('job_id') not in state['transport_bindings'].values():
                    raise TaskError('A bound workflow transport job is required')
                if operation == 'mark_dispatched':
                    self._execution_ready(state)
                queue = transport.embedded_apply(queue, operation, args, principal,
                                                 self._topology(state), self._manifests(state))
            record = {'request_id': request_id, 'operation': operation, 'arguments': copy.deepcopy(args),
                      'principal': principal, 'fingerprint': fingerprint,
                      'result': {'run_id': self.run_id, 'job_id': args.get('job_id'),
                                 'job': copy.deepcopy(queue['jobs'].get(args.get('job_id')))}}
            if artifact is not None:
                record['artifact_sha256'] = digest(artifact)
            queue['requests'][request_id] = record
            state['transport'] = queue
            committed = True
        payload = {'request_id': request_id, 'operation': operation, 'arguments': copy.deepcopy(args),
                   'principal': principal, 'fingerprint': fingerprint}
        if artifact is not None:
            payload.update(artifact_sha256=digest(artifact), artifact_kind='synthetic_transport_batch')
        result = self._transition('transport.' + operation, principal, update, payload, artifact)
        return copy.deepcopy(result['transport']['requests'][request_id]), committed, result

    def prepare_transport(self, actor_id, route_id, job_id, request_id):
        transport.ident(route_id); transport.ident(job_id)
        return self._transport_transition('prepare_route', actor_id, request_id,
                                          {'route_id': route_id, 'job_id': job_id})[0]

    def transport_act(self, operation, principal, request_id, **args):
        return self._transport_transition(operation, principal, request_id, args)[0]

    def dispatch_transport(self, job_id, adapter, principal, request_id):
        record, committed, dispatched = self._transport_transition(
            'mark_dispatched', principal, request_id, {'job_id': job_id})
        if not committed:
            return {'request': record, 'batch': None, 'replayed': True}
        current = self.state
        verify_sources(current['definition'])
        self._execution_ready(current)
        if (self.session is None or self.session != current['session']
                or current['transport']['session'] != self.session
                or current['transport']['jobs'].get(job_id) != dispatched['transport']['jobs'].get(job_id)
                or current['transport']['outbox'].get(job_id) != dispatched['transport']['outbox'].get(job_id)
                or current['transport']['jobs'][job_id]['control'] != 'active'
                or current['transport']['jobs'][job_id]['cancel_requested']
                or any(j['rack_id'] == current['definition']['rack_instance'] and j['control'] == 'held'
                       for j in current['transport']['jobs'].values())):
            raise TaskError('Dispatch superseded or held before adapter invocation')
        envelope = transport.embedded_envelope(dispatched['transport'], job_id, self._topology(dispatched))
        try:
            batch = adapter.submit(copy.deepcopy(envelope))
            encoded(batch)
        except BaseException:
            self.transport_act('hold', principal, 'DispatchFailure.' + digest(request_id.encode())[:32],
                               job_id=job_id, reason='adapter_failure')
            raise
        return {'request': record, 'batch': copy.deepcopy(batch), 'replayed': False}

    def ingest_transport(self, batch):
        if not isinstance(batch, list):
            raise TaskError('Explicit synthetic transport batch required')
        artifact = encoded(batch).encode()
        for message in batch:
            if (not isinstance(message, dict) or set(message) != {'principal', 'request_id', 'operation', 'args'}
                    or message['operation'] not in {'worker_claim', 'observe'} or not isinstance(message['args'], dict)):
                raise TaskError('Exact synthetic transport message fields required')
        return [self._transport_transition(message['operation'], message['principal'], message['request_id'],
                                           message['args'], artifact)[0] for message in batch]

    def _transport_audit(self, state, completing=False):
        self._audit_transport_context(state)
        for record in state['transport']['requests'].values():
            if record.get('artifact_sha256'):
                self.journal.artifact(record['artifact_sha256'])
        if self._queue_uncertain(state):
            raise TaskError('Unresolved transport prevents workflow completion or disposition')
        if completing and not self._transport_passed(state):
            raise TaskError('Every workflow route requires an undisputed completed transport')

    def _audit(self, state, completing=False):
        super()._audit(state, completing)
        self._transport_audit(state, completing)

    @classmethod
    def _transport_passed(cls, state):
        queue = state['transport']
        return (set(state['transport_bindings']) == set(cls._routes(state))
                and all(j['phase'] == 'completed' and j['control'] == 'active' for j in queue['jobs'].values())
                and not any(entry['status'] in {'pending', 'conflict', 'stale'} for entry in queue['inbox'].values()))

    def report(self):
        with self.journal._reading():
            result = super().report()
            state = self.state
            verify_sources(state['definition'])
            self._audit_transport_context(state)
            for record in state['transport']['requests'].values():
                if record.get('artifact_sha256'):
                    self.journal.artifact(record['artifact_sha256'])
            actual = {resource for resource, owner in self.journal.owners().items() if owner == self.run_id}
            if actual != set(state['resources']) or state['resources'] != self._resources(state):
                raise TaskError('Journal reservations differ from the T2 owner projection')
            result.update(transport=copy.deepcopy(state['transport']),
                          transport_bindings=copy.deepcopy(state['transport_bindings']),
                          transport_admitted=state['transport_admitted'],
                          transport_passed=self._transport_passed(state),
                          passed=result['passed'] and self._transport_passed(state),
                          execution_mode='teleportation_mock', transport_time_s=0,
                          existing_workflow_integrated=True)
            result['limitations'] += [
                'Transport uses explicit synthetic role attestations and zero-time teleportation mocks only.',
                'Rack, original identities and occupied endpoints remain held after biological completion; no stock handoff.',
                'One bound job per route; reconciled cancellation has no automatic retry or normal success.',
                'No release API for terminal transport conflicts; the affected rack remains quarantined.']
            return result
