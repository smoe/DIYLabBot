"""Durable T1 synthetic rack transport in one existing owner journal.

Jobs, queue state, role receipts and subclaims share the root event transaction.
Adapters receive no database access. A committed dispatch is never automatically
repeated, and adapter output is not accepted as an inventory observation here.
"""
import copy
from pathlib import Path
import re
import uuid

import async_transport_domain as domain
import material_ledger as ledger
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = ('scripts/async_transport.py', 'scripts/async_transport_adapters.py',
                 'scripts/run_async_transport.py')
REPORT_FORMAT = 'solidcraftbot.async-lab-transport-report/1'


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', value):
        raise TaskError('Explicit 1-160 character ASCII '+label+' required')
    return value


def verify_sources(definition):
    pins = definition.get('source_files_sha256')
    if not isinstance(pins, dict) or not pins:
        raise TaskError('Pinned transport definition required')
    for name, expected in pins.items():
        path = Path(name)
        if (not isinstance(name, str) or path.is_absolute() or '..' in path.parts
                or not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected)):
            raise TaskError('Invalid transport source pin')
        path = (ROOT/path).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or digest(path.read_bytes()) != expected:
            raise TaskError('Transport source changed; no implicit migration: '+name)


def _definition(source):
    definition = copy.deepcopy(domain.load_definition() if source is None else domain.load_definition(source))
    pins = definition['source_files_sha256']
    for name in RUNTIME_FILES:
        path = ROOT/name
        if not path.is_file():
            raise TaskError('Missing transport runtime source: '+name)
        actual = digest(path.read_bytes())
        if name in pins and pins[name] != actual:
            raise TaskError('Conflicting transport runtime pin: '+name)
        pins[name] = actual
    verify_sources(definition)
    return definition


class AsyncTransport:
    def __init__(self, journal, run_id, session=None):
        self.journal, self.run_id, self.session = journal, run_id, session
        self._load(verify=True)

    def _load(self, *, verify=False):
        state, revision = self.journal.get_current(self.run_id, verify=verify)
        if state.get('run_id') != self.run_id or state.get('format') != domain.STATE_FORMAT:
            raise TaskError('Wrong asynchronous transport root')
        domain.audit(state)
        verify_sources(state['definition'])
        return state, revision

    @classmethod
    def create(cls, journal, run_id, source=None):
        _identifier(run_id, 'root identity')
        definition = _definition(source)
        session = uuid.uuid4().hex
        state = domain.initial_state(definition, run_id, session)
        if state['admitted'] or state['inventory'] or state['resources']:
            raise TaskError('Creation must remain unadmitted with no inventory or claimed resources')
        verify_sources(definition)
        journal.create(run_id, state, immutable_definition=True)
        return cls(journal, run_id, session)

    @classmethod
    def open(cls, journal, run_id, resume=False, *, principal=None, request_id=None):
        if type(resume) is not bool:
            raise TaskError('Explicit boolean resume decision required')
        flow = cls(journal, run_id)
        if not resume:
            return flow
        _identifier(principal, 'resume principal')
        request_id = request_id or 'Resume.'+uuid.uuid4().hex
        before, _ = flow._load()
        previous = before['requests'].get(request_id)
        if previous is not None:
            if (previous.get('operation') != 'resume' or previous.get('principal') != principal
                    or previous.get('arguments', {}).get('session') != before['session']):
                raise TaskError('Resume request is conflicting or has been superseded')
            flow.session = before['session']
            flow._act('resume', principal, request_id, previous['arguments'], allow_resume=True)
            return flow
        session = uuid.uuid4().hex
        flow._act('resume', principal, request_id, {'session': session}, allow_resume=True)
        flow.session = session
        return flow

    @property
    def state(self):
        return self._load()[0]

    def _act(self, operation, principal, request_id, args, *, allow_resume=False, artifact=None):
        _identifier(principal, 'principal'); _identifier(request_id, 'request identity')
        if operation == 'resume' and not allow_resume:
            raise TaskError('Use explicit open(resume=True) to replace a session')
        before, revision = self._load()
        if not allow_resume and (self.session is None or self.session != before['session']):
            raise TaskError('Stale or read-only transport session; explicitly resume and reconcile')
        fingerprint = digest(encoded({'operation': operation, 'arguments': args}).encode())
        existing = before['requests'].get(request_id)
        if existing is not None:
            if (existing.get('principal') != principal or existing.get('fingerprint') != fingerprint
                    or existing.get('operation') != operation or existing.get('arguments') != args):
                raise TaskError('Request identity has conflicting arguments or principal')
            return copy.deepcopy(existing), False, before
        after = domain.apply(before, operation, copy.deepcopy(args), principal)
        job_id = args.get('job_id')
        record = {'request_id': request_id, 'operation': operation, 'arguments': copy.deepcopy(args),
                  'principal': principal, 'fingerprint': fingerprint, 'committed_revision': revision+1,
                  'result': {'run_id': self.run_id, 'admitted': after['admitted'],
                             'job_id': job_id, 'job': copy.deepcopy(after['jobs'].get(job_id))}}
        after['requests'][request_id] = record
        domain.audit(after); verify_sources(after['definition'])
        payload = {'operation': operation, 'arguments': copy.deepcopy(args), 'principal': principal,
                   'request_id': request_id, 'fingerprint': fingerprint, 'evidence': 'synthetic_request'}
        if artifact is not None:
            payload['artifact_sha256'] = digest(artifact)
            payload['artifact_kind'] = 'synthetic_ingest_batch'
        self.journal.append(self.run_id, revision, 'transport.'+operation, payload, after, artifact=artifact)
        # Return detached values only. Neither caller nor adapter owns journal state.
        return copy.deepcopy(record), True, copy.deepcopy(after)

    def act(self, operation, principal, request_id, **args):
        return self._act(operation, principal, request_id, args)[0]

    def dispatch(self, job_id, adapter, principal, request_id):
        record, committed, dispatched = self._act('mark_dispatched', principal, request_id, {'job_id': job_id})
        if not committed:
            return {'request': record, 'batch': None, 'replayed': True}
        envelope = domain.envelope(dispatched, job_id)
        # A competing session/epoch may have superseded this dispatcher before
        # the call. CAS cannot retract an already issued physical command.
        current, _ = self._load()
        current_job = current['jobs'].get(job_id)
        rack_held = any(job['rack_id'] == envelope['rack_id'] and job['control'] == 'held'
                        for job in current['jobs'].values())
        if (self.session != current['session'] or current['assignment_epoch'] != dispatched['assignment_epoch']
                or current['outbox'].get(job_id) != dispatched['outbox'][job_id]
                or current_job != dispatched['jobs'][job_id]
                or current_job['control'] != 'active' or current_job['cancel_requested']
                or rack_held):
            raise TaskError('Dispatch was superseded or held; do not invoke the adapter')
        try:
            batch = adapter.submit(copy.deepcopy(envelope))
            encoded(batch)  # Only an explicit finite JSON batch can be returned.
        except BaseException:
            # The durable dispatched intent and reservations already exist. This
            # records uncertainty, never a fabricated observation/nonperformance.
            hold_id = 'DispatchFailure.'+digest(request_id.encode())[:32]
            self._act('hold', principal, hold_id, {'job_id': job_id, 'reason': 'adapter_failure'})
            raise
        return {'request': record, 'batch': copy.deepcopy(batch), 'replayed': False}

    def ingest(self, batch):
        """Trusted synthetic helper; each message is atomically accepted separately.

        This is no authenticated network endpoint. Principals must come from a
        trusted adapter invocation; T3 must supply authenticated server context.
        """
        if not isinstance(batch, list):
            raise TaskError('Explicit synthetic message batch required')
        artifact = encoded(batch).encode()
        for message in batch:
            if (not isinstance(message, dict) or set(message) != {'principal', 'request_id', 'operation', 'args'}
                    or message['operation'] not in {'worker_claim', 'observe'} or not isinstance(message['args'], dict)):
                raise TaskError('Exact synthetic claim/observation message fields required')
        return [self._act(message['operation'], message['principal'], message['request_id'],
                          message['args'], artifact=artifact)[0] for message in batch]

    def report(self):
        # History, resource rows and allocation audit must describe one database
        # snapshot even while another connection commits an independent job.
        with self.journal._reading():
            return self._report_snapshot()

    def _report_snapshot(self):
        trace = self.journal.history(self.run_id)
        for event in trace:
            domain.audit(event['state'])
            checksum = event['payload'].get('artifact_sha256')
            if checksum is not None:
                self.journal.artifact(checksum)
        state = trace[-1]['state']; verify_sources(state['definition'])
        if state['admitted']:
            ledger.audit(state)
        owners = {name for name, owner in self.journal.owners().items() if owner == self.run_id}
        if owners != set(state['resources']):
            raise TaskError('Native journal reservations differ from transport projection')
        self.journal.audit_material_allocations()
        completed = [key for key, job in state['jobs'].items()
                     if job['phase'] == 'completed' and job['control'] == 'active']
        unresolved = [key for key, job in state['jobs'].items()
                      if job['control'] != 'active' or job['phase'] not in domain.TERMINAL]
        unresolved_inbox = [key for key, entry in state['inbox'].items()
                            if entry['status'] in {'pending', 'conflict', 'stale'}]
        return {'format': REPORT_FORMAT, 'run_id': self.run_id, 'mode': 'synthetic_only',
                'admitted': state['admitted'], 'jobs': copy.deepcopy(state['jobs']),
                'inventory': copy.deepcopy(state['inventory']), 'rack_placements': copy.deepcopy(state['rack_placements']),
                'bookings': copy.deepcopy(state['bookings']), 'resources': list(state['resources']),
                'completed_jobs': completed, 'unresolved_jobs': unresolved,
                'unresolved_inbox': unresolved_inbox,
                'passed': (state['admitted'] and bool(state['jobs'])
                           and len(completed) == len(state['jobs']) and not unresolved_inbox),
                'event_count': len(trace), 'journal_head_sha256': trace[-1]['sha256'],
                'source_files_sha256': copy.deepcopy(state['definition']['source_files_sha256']),
                'cross_owner_stock': False, 'quantity_changes': False,
                'execution_mode': 'teleportation_mock', 'transport_time_s': 0,
                'robot_motion_executed': False, 'hardware_executed': False,
                'network_executed': False, 'existing_workflow_integrated': False,
                'limitations': ['A fresh synthetic owner fixture, not T2 integration into an existing biological run.',
                    'Zero simulated travel time supplies no real motion, handover, storage or safety qualification.',
                    'Sender, courier and receiver statements remain explicitly synthetic role receipts.',
                    'All initial identities and quantities remain bound to this owner; no independent stock continuation.',
                    'T1 has no release API for terminal jobs held by late conflicting receipts; the affected rack remains quarantined.']}
