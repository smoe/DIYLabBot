"""Authenticated T3 command boundary over the existing synthetic T2 owner.

The service has no inventory, independent transport state machine or effect
outbox. Original HTTP bodies and authenticated grants commit with the existing
transport request receipt. A service boot never resumes or dispatches a job.
"""
import base64
import copy
import fcntl
import json
import os
from pathlib import Path
import threading
import uuid

import async_transport_domain as domain
from async_transport import verify_sources
from lab_transport_access import Access
from lab_transport_workflow import TransportWorkflow
from lab_workflow import TERMINAL
from lab_workflow_stages import ADAPTERS
from manual_tasks import Journal, TaskError, digest, encoded
from manual_workflow import ObservationError

ROOT = Path(__file__).resolve().parents[1]
INTERFACE = 'solidcraftbot.lab-transport-network-protocol/1'
FORMAT = 'solidcraftbot.synthetic-lab-network-state/3'
DEFINITION_FORMAT = 'solidcraftbot.synthetic-lab-network-workflow/3'
NETWORK_FORMAT = 'solidcraftbot.lab-transport-network-state/1'


class CoreError(TaskError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def _uuid(value):
    if not isinstance(value, str):
        raise CoreError('invalid_identity', 'A persistent server identity is required', 400)
    try:
        return str(uuid.UUID(value))
    except ValueError as error:
        raise CoreError('invalid_identity', 'Invalid server identity', 400) from error


def _request_identity(operation, args, context):
    return digest(encoded({'operation': operation, 'arguments': args,
                           'request_context': context}).encode())


def _context(context):
    domain.exact(context, 'subject grant interface wire_sha256 transport_channel operation owner_fence', 'authenticated request context')
    domain.require(isinstance(context['subject'], str) and bool(context['subject']), 'Authenticated account required')
    domain.exact(context['grant'], 'id kind resource_id', 'authenticated grant')
    domain.ident(context['grant']['id']); domain.ident(context['grant']['resource_id'])
    domain.require(context['grant']['kind'] in {'owner', 'observer', 'endpoint', 'agent'}, 'Unknown authenticated grant')
    domain.require(context['interface'] == INTERFACE and context['transport_channel'] in {'https', 'in_process'},
                   'Explicit T3 interface channel required')
    domain.checksum(context['wire_sha256'])
    if context['operation'] == 'attest':
        domain.require(context['owner_fence'] is None, 'Attestations bind the original job epoch')
    else:
        domain.exact(context['owner_fence'], 'boot_id assignment_epoch', 'owner context fence')
        _uuid(context['owner_fence']['boot_id'])
        domain.require(type(context['owner_fence']['assignment_epoch']) is int
                       and context['owner_fence']['assignment_epoch'] > 0, 'Positive owner epoch required')


class NetworkWorkflow(TransportWorkflow):
    STATE_FORMAT = FORMAT
    DEFINITION_FORMAT = DEFINITION_FORMAT

    @classmethod
    def _load_definition(cls, source, runtime_sources):
        from lab_transport_network_sources import load
        return load(source, runtime_sources=runtime_sources)

    @classmethod
    def create(cls, journal, source=None, run_id=None, *, server_uuid=None):
        if source is None:
            from lab_transport_network_sources import SOURCE
            source = SOURCE
        return super().create(journal, source, run_id,
                              initial_context={'server_uuid': _uuid(server_uuid or str(uuid.uuid4()))})

    @classmethod
    def _initialize_transport_extension(cls, state, initial_context):
        domain.exact(initial_context, 'server_uuid', 'network owner binding')
        state['network'] = {'format': NETWORK_FORMAT,
                            'server_uuid': _uuid(initial_context['server_uuid']), 'boot_id': None}

    @classmethod
    def _format(cls, state):
        super()._format(state)
        domain.exact(state.get('network'), 'format server_uuid boot_id', 'network owner state')
        domain.require(state['network']['format'] == NETWORK_FORMAT, 'Unsupported network owner state')
        _uuid(state['network']['server_uuid'])
        if state['network']['boot_id'] is not None: _uuid(state['network']['boot_id'])

    def _terminal_transition_allowed(self, kind):
        return kind == 'transport.network_resume' or super()._terminal_transition_allowed(kind)

    def _before_transition(self, state, kind):
        guard = getattr(self, '_authorization_guard', None)
        if guard is not None: guard()
        super()._before_transition(state, kind)

    def _validate_transport_request(self, state, operation, args, principal, request_context):
        if request_context is None: return
        _context(request_context)
        if request_context['operation'] != 'attest':
            fence = request_context['owner_fence']
            if (fence['boot_id'] != getattr(self, '_service_boot_id', None)
                    or fence['assignment_epoch'] != state['transport']['assignment_epoch']):
                raise CoreError('stale_owner_context', 'Owner context changed before the root transaction')

    def _after_transition(self, before, state, kind):
        super()._after_transition(before, state, kind)
        self._format(state)
        for request_id in set(state['transport']['requests']) - set(before['transport']['requests']):
            record = state['transport']['requests'][request_id]
            context = record.get('request_context')
            if context is None: continue
            _context(context)
            domain.require(record.get('artifact_sha256') == context['wire_sha256'],
                           'Wire evidence and authenticated request differ')
            record['response'] = {'request_id': request_id, 'operation': context['operation'],
                                  'outcome': 'committed', 'result': copy.deepcopy(record['result'])}
        guard = getattr(self, '_authorization_guard', None)
        if guard is not None: guard()

    @classmethod
    def workflow_reconcile_available(cls, state):
        stage_id = state['active_stage']; stage = state['stages'][stage_id]
        return (stage_id in ADAPTERS and state['status'] == 'held'
                and stage['status'] in {'ready', 'waiting_transport'} and stage['actor_id'] is None
                and state['recovery_required'] == 'session_restarted'
                and stage['recovery_required'] == 'session_restarted'
                and not cls._payload_claimed(state)
                and not stage.get('measurements') and not stage.get('preparations')
                and not stage.get('pending_measurement') and not stage.get('pending_operation')
                and state['logical_time_s'] < state['deadline_s']
                and (stage['deadline_s'] is None or state['logical_time_s'] < stage['deadline_s']))

    @classmethod
    def dispatch_available(cls, state, job_id):
        """Ask the existing pure domain proposal without applying an effect."""
        try:
            cls._execution_ready(state)
            domain.embedded_apply(state['transport'], 'mark_dispatched', {'job_id': job_id},
                                  cls._topology(state)['owner_principal'],
                                  cls._topology(state), cls._manifests(state))
        except TaskError:
            return False
        return True

    def _apply_transport_extension(self, state, operation, args, principal):
        if operation != 'workflow_reconcile':
            return super()._apply_transport_extension(state, operation, args, principal)
        domain.exact(args, 'observations workspace_clear arm_clear gripper_empty manifest_confirmed',
                     'unbegun workflow boundary reconciliation')
        domain.require(principal == self._topology(state)['owner_principal'], 'Workflow owner required')
        domain.require(self.workflow_reconcile_available(state),
                       'Only an unbegun manual boundary can be reconciled through this interface')
        domain.require(all(args[field] is True for field in
                           ['workspace_clear', 'arm_clear', 'gripper_empty', 'manifest_confirmed']),
                       'Explicit synthetic inventory and clearance confirmations required')
        # A rejected owner reconciliation is not a new observation effect.
        # The parent device API journals ObservationError as a separate hold;
        # this network boundary instead rejects malformed inventory before any
        # Root effect, so it cannot produce an effect without its wire receipt.
        try:
            self._observations(state, args['observations'])
        except ObservationError as error:
            raise TaskError('Complete original inventory observations required') from error
        stage_id = state['active_stage']; stage = state['stages'][stage_id]
        adapter = ADAPTERS[stage_id](self, state, stage_id)
        device = {'blank_still_valid': False} if stage_id == 'nanodrop' else {'calibration_still_valid': False}
        try:
            adapter._reconcile(adapter.state, principal, observations=args['observations'],
                               workspace_clear=True, **device)
        except ObservationError as error:
            raise TaskError('Unbegun device inventory reconciliation rejected') from error
        domain.require(stage['recovery_required'] is None, 'Boundary reconciliation remains unresolved')
        state['recovery_required'] = None
        state['status'] = 'running'

    def resume_network(self, principal, request_id, args, request_context, artifact, boot_id, guard):
        """Explicit owner takeover and its receipt share one root transaction."""
        before, revision = self.journal.get_current(self.run_id, verify=True)
        self._format(before); verify_sources(before['definition']); guard()
        fingerprint = _request_identity('network_resume', args, request_context)
        previous = before['transport']['requests'].get(request_id)
        if previous is not None:
            if (previous['principal'] != principal or previous['fingerprint'] != fingerprint):
                raise CoreError('request_conflict', 'Request identity has different authenticated intent')
            return copy.deepcopy(previous), before, False
        self._validate_transport_request(before, 'network_resume', args, principal, request_context)
        domain.require(principal == self._topology(before)['owner_principal'], 'Owner resume required')
        state = copy.deepcopy(before)
        session = uuid.uuid4().hex
        state['session'] = session
        state['network']['boot_id'] = boot_id
        state['transport'] = domain.embedded_apply(state['transport'], 'resume', {'session': session},
                                                   principal, self._topology(state), self._manifests(state))
        if state['status'] not in TERMINAL and state['resources']:
            stage = state['stages'][state['active_stage']]
            reason = ('cf01_context_lost' if state['active_stage'] == 'cf01' and stage['status'] != 'ready'
                      else 'session_restarted')
            state['recovery_required'] = state['recovery_required'] or reason
            stage['recovery_required'] = stage['recovery_required'] or reason
            if state['status'] != 'cancelling': state['status'] = 'held'
        record = {'request_id': request_id, 'operation': 'network_resume', 'arguments': copy.deepcopy(args),
                  'principal': principal, 'fingerprint': fingerprint,
                  'request_context': copy.deepcopy(request_context), 'artifact_sha256': digest(artifact),
                  'result': {'run_id': self.run_id, 'job_id': None, 'job': None}}
        state['transport']['requests'][request_id] = record
        self._after_transition(before, state, 'transport.network_resume')
        guard()
        self.journal.append(self.run_id, revision, 'transport.network_resume', {
            'actor_id': principal, 'evidence': 'authenticated_synthetic_input',
            'request_id': request_id, 'operation': 'network_resume', 'arguments': args,
            'request_context': request_context, 'artifact_sha256': digest(artifact),
            'artifact_kind': 'authenticated_transport_request'}, state, artifact=artifact)
        self.session = session
        return copy.deepcopy(state['transport']['requests'][request_id]), state, True

    def report(self):
        result = super().report()
        result['limitations'] = [
            'No instrument-network execution, hardware, new CAD geometry or executed robot paths'
            if item == 'No network, hardware, new CAD geometry or executed robot paths' else item
            for item in result['limitations']]
        network_used = any(record.get('request_context', {}).get('transport_channel') == 'https'
                           for record in result['transport']['requests'].values())
        result.update(network_executed=network_used, transport_network_executed=network_used,
                      instrument_network_executed=False,
                      server_uuid=self.state['network']['server_uuid'])
        result['limitations'] += [
            'Authentication identifies a configured local account, not a verified physical person or handover.',
            'HTTPS transport evidence does not qualify LAN deployment, instruments, robot motion or safety.',
            'Only an unbegun manual boundary can be reconciled through the courier interface.']
        return result


class Service:
    """One private service binding; every request opens its own journal connection."""
    def __init__(self, directory, source=None, clock=None):
        self.directory = Path(directory).resolve()
        domain.require(self.directory.is_relative_to(ROOT / 'exports'), 'Private service data must remain under exports/')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        domain.require(self.directory.stat().st_mode & 0o077 == 0, 'Service directory must be private')
        for name in ['service.json', 'users.json']:
            file = self.directory / name
            domain.require(not file.is_symlink() and file.resolve().parent == self.directory
                           and file.is_file() and file.stat().st_mode & 0o077 == 0,
                           'Private non-symlink service configuration required')
        self._lock_file = (self.directory / 'server.lock').open('a+b')
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._lock_file.close()
            raise CoreError('service_busy', 'Another service owns this private directory') from error
        try:
            from lab_transport_network_sources import SOURCE, load
            definition = load(SOURCE if source is None else source)
            self.contract = definition['network_interface']['contract']
            config = domain._json((self.directory / 'service.json').read_bytes())
            domain.exact(config, 'format store run_id server_uuid', 'private service binding')
            domain.require(config['format'] == 'solidcraftbot.lab-transport-service/1', 'Unsupported private service binding')
            self.store = Path(config['store']).resolve() if Path(config['store']).is_absolute() else (ROOT / config['store']).resolve()
            domain.require(self.store.is_relative_to(ROOT / 'exports') and self.store.is_file(),
                           'An existing explicitly bound journal under exports/ is required')
            self.run_id = domain.ident(config['run_id']); self.server_uuid = _uuid(config['server_uuid'])
            self.boot_id = str(uuid.uuid4())
            users = domain._json((self.directory / 'users.json').read_bytes())
            domain.exact(users, 'format users', 'private users file')
            domain.require(users['format'] == 'solidcraftbot.lab-transport-users/1', 'Unsupported local accounts file')
            self.access = Access(users['users'], self.server_uuid, **({'clock': clock} if clock is not None else {}))
            self._write_session = None
            self._closed = False
            self._session_lock = threading.RLock()
            with Journal(self.store) as journal:
                flow = NetworkWorkflow(journal, self.run_id)
                state = flow.state
                verify_sources(state['definition'])
                domain.require(state['network']['server_uuid'] == self.server_uuid, 'Root belongs to another service')
                domain.require(state['definition']['effective_profile_sha256'] == definition['effective_profile_sha256'],
                               'Service and root source composition differ')
        except BaseException:
            self._lock_file.close()
            raise

    def close(self):
        with self._session_lock:
            self._closed = True
            self._write_session = None
        self._lock_file.close()

    def _ensure_open(self):
        if self._closed: raise CoreError('service_closed', 'Service is closed', 503)

    def info(self):
        self._ensure_open()
        return {'format': 'solidcraftbot.lab-transport-network-info/1',
                'server_uuid': self.server_uuid, 'boot_id': self.boot_id, 'run_id': self.run_id,
                'mode': 'synthetic_only', 'tls_required': True,
                'paths': copy.deepcopy(self.contract['paths'])}

    def session(self, context):
        identity = self.access.validate_context(context)
        return {**self.info(), **identity}

    def _flow(self, journal):
        return NetworkWorkflow(journal, self.run_id, self._write_session)

    def _check_run(self, run_id):
        self._ensure_open()
        if run_id != self.run_id: raise CoreError('not_found', 'Unknown run', 404)

    @staticmethod
    def _matching_grant(context, grant, state):
        topology = state['definition']['transport']['topology']
        kind, resource = grant['kind'], grant['resource_id']
        if kind == 'owner': return resource == state['run_id'] and context['principal'] == topology['owner_principal']
        if kind == 'observer': return resource == state['run_id']
        values = topology['endpoints'] if kind == 'endpoint' else topology['agents']
        return any(item['id'] == resource and item['principal'] == context['principal'] for item in values)

    def _grants(self, context, state):
        identity = self.access.validate_context(context)
        return [grant for grant in identity['grants'] if self._matching_grant(identity, grant, state)]

    def _grant(self, context, state, grant_id):
        found = [grant for grant in self._grants(context, state) if grant['id'] == grant_id]
        if len(found) != 1: raise CoreError('forbidden', 'Account is not authorized for this grant', 403)
        return found[0]

    @staticmethod
    def _can_see(grants, job):
        return any(grant['kind'] in {'owner', 'observer'}
                   or grant['kind'] == 'endpoint' and grant['resource_id'] in {job['source_endpoint'], job['target_endpoint']}
                   or grant['kind'] == 'agent' and grant['resource_id'] == job['agent_id'] for grant in grants)

    @staticmethod
    def _attest_roles(grant, job):
        if grant['kind'] == 'endpoint':
            return (['pickup_release'] if grant['resource_id'] == job['source_endpoint'] else []) + (
                ['delivery_accept'] if grant['resource_id'] == job['target_endpoint'] else [])
        if grant['kind'] == 'agent' and grant['resource_id'] == job['agent_id']:
            return ['pickup_accept', 'delivery_release']
        return []

    def _cursor(self, journal, sequence, checksum):
        return {'server_uuid': self.server_uuid, 'run_id': self.run_id,
                'sequence': sequence, 'sha256': checksum}

    def _check_cursor(self, journal, cursor):
        if cursor is None: return
        try:
            if isinstance(cursor, str):
                if not 0 < len(cursor) <= 4096: raise ValueError('cursor length')
                cursor = domain._json(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
            domain.exact(cursor, 'server_uuid run_id sequence sha256', 'history cursor')
            domain.require(cursor['server_uuid'] == self.server_uuid and cursor['run_id'] == self.run_id,
                           'Cursor belongs to another authority')
            domain.require(type(cursor['sequence']) is int and cursor['sequence'] >= 1, 'Invalid cursor sequence')
            domain.checksum(cursor['sha256'])
            row = journal.connection.execute('SELECT sha256 FROM events WHERE run_id=? AND sequence=?',
                                             (self.run_id, cursor['sequence'])).fetchone()
            domain.require(row is not None and row[0] == cursor['sha256'], 'History cursor is not a verified prefix')
        except (ValueError, TypeError, KeyError) as error:
            raise CoreError('cursor_mismatch', 'History cursor belongs to another or rolled-back journal') from error

    def _snapshot(self, context, journal):
        state, revision = journal.get_current(self.run_id)
        NetworkWorkflow._format(state); verify_sources(state['definition'])
        grants = self._grants(context, state)
        if not grants: raise CoreError('forbidden', 'Account has no scope for this run', 403)
        checksum = journal.connection.execute('SELECT sha256 FROM events WHERE run_id=? AND sequence=?',
                                             (self.run_id, revision)).fetchone()[0]
        fence = {'boot_id': self.boot_id, 'assignment_epoch': state['transport']['assignment_epoch']}
        writable = bool(self._write_session and self._write_session == state['session']
                        and state['network']['boot_id'] == self.boot_id)
        jobs = []
        for job_id, job in state['transport']['jobs'].items():
            if not self._can_see(grants, job): continue
            envelope = domain.embedded_envelope(state['transport'], job_id, state['definition']['transport']['topology'])
            actions = []
            for grant in grants:
                if writable and state['transport']['outbox'][job_id]['status'] in {'dispatched', 'uncertain'}:
                    actions += [{'grant_id': grant['id'], 'operation': 'attest', 'role': role}
                                for role in self._attest_roles(grant, job)]
                if writable and grant['kind'] == 'owner' and job['phase'] not in domain.TERMINAL:
                    actions += [{'grant_id': grant['id'], 'operation': op, 'args_template': dict(fence)}
                                for op in ['hold', 'cancel']]
                    if job['control'] == 'held':
                        actions.append({'grant_id': grant['id'], 'operation': 'reconcile', 'args_template': dict(fence)})
                    if (state['transport']['outbox'][job_id]['status'] == 'pending'
                            and NetworkWorkflow.dispatch_available(state, job_id)):
                        actions.append({'grant_id': grant['id'], 'operation': 'dispatch', 'args_template': dict(fence)})
            jobs.append({**envelope, 'phase': job['phase'], 'control': job['control'],
                         'hold_reason': job['hold_reason'], 'receipts': copy.deepcopy(job['receipts']),
                         'allowed_actions': actions})
        owners = [grant for grant in grants if grant['kind'] == 'owner']
        reconcile_allowed = bool(writable and owners and NetworkWorkflow.workflow_reconcile_available(state))
        observations = [{'vessel_id': key, 'location': copy.deepcopy(vessel['location']),
                         **({'sample_id': vessel['sample_id']} if vessel['origin'] == 'original' else {})}
                        for key, vessel in state['inventory']['vessels'].items()] if owners else []
        routes = []
        for route in state['definition']['transport']['routes']:
            if route['id'] in state['transport_bindings']: continue
            ready = writable
            try:
                NetworkWorkflow._execution_ready(state)
                NetworkWorkflow._route_ready(state, route)
            except TaskError:
                ready = False
            routes.append({**copy.deepcopy(route), 'allowed_actions': [
                {'operation': 'prepare_route', 'grant_id': grant['id'], 'args_template': {
                    **fence, 'route_id': route['id']}} for grant in owners] if ready else []})
        return {**self.info(), 'subject': context['subject'], 'principal': context['principal'],
                'grants': copy.deepcopy(grants), 'revision': revision,
                'cursor': self._cursor(journal, revision, checksum),
                'assignment_epoch': state['transport']['assignment_epoch'],
                'write_session_available': writable,
                'root_status': state['status'], 'recovery_required': state['recovery_required'],
                'jobs': jobs, 'routes': routes,
                'workflow_reconcile': {'allowed': reconcile_allowed,
                    'grant_id': owners[0]['id'] if owners else None,
                    'args_template': {'scope': 'workflow', 'observations': observations, **fence},
                    'reason': ('An unbegun manual boundary needs explicit synthetic inventory reconciliation'
                               if reconcile_allowed else 'Active instrument attempts require local reconciliation')},
                'owner_actions': [{'operation': 'resume', 'grant_id': grant['id'], 'args_template': dict(fence)}
                                  for grant in owners]}

    def snapshot(self, context, run_id, cursor=None):
        self._check_run(run_id)
        with Journal(self.store) as journal, journal._reading():
            state, _ = journal.get_current(self.run_id)
            if not self._grants(context, state): raise CoreError('forbidden', 'Account has no scope for this run', 403)
            self._check_cursor(journal, cursor)
            return self._snapshot(context, journal)

    def receipt(self, context, run_id, request_id, cursor=None):
        self._check_run(run_id); domain.ident(request_id)
        with Journal(self.store) as journal, journal._reading():
            state, _ = journal.get_current(self.run_id)
            if not self._grants(context, state): raise CoreError('forbidden', 'Account has no scope for this run', 403)
            self._check_cursor(journal, cursor)
            record = state['transport']['requests'].get(request_id)
            if record and record.get('request_context', {}).get('subject') != context['subject']:
                raise CoreError('forbidden', 'Request receipt belongs to another account', 403)
            return {'receipt': copy.deepcopy(record), 'replayed': bool(record),
                    'snapshot': self._snapshot(context, journal)}

    def _owner_fence(self, state, args):
        if (args.get('boot_id') != self.boot_id or type(args.get('assignment_epoch')) is not int
                or args['assignment_epoch'] != state['transport']['assignment_epoch']):
            raise CoreError('stale_owner_context', 'Refresh and explicitly confirm the current owner context')
        return {key: copy.deepcopy(value) for key, value in args.items()
                if key not in {'boot_id', 'assignment_epoch'}}

    def request(self, context, run_id, request_id, operation, args, wire_bytes,
                *, grant_id, cursor=None, transport_channel='in_process'):
        self._check_run(run_id); domain.ident(request_id)
        if not isinstance(args, dict) or not isinstance(operation, str):
            raise CoreError('invalid_request', 'Explicit operation and argument object required', 400)
        if not isinstance(wire_bytes, bytes) or len(wire_bytes) > self.contract['limits']['max_body_bytes']:
            raise CoreError('invalid_request', 'A bounded original request body is required', 400)
        body = domain._json(wire_bytes)
        expected = {'request_id': request_id, 'grant_id': grant_id, 'operation': operation, 'args': args}
        if body != expected or set(body) != set(expected):
            raise CoreError('invalid_request', 'Original request and parsed operation differ', 400)
        if operation not in {'resume', 'prepare_route', 'dispatch', 'attest', 'hold', 'cancel', 'reconcile'}:
            raise CoreError('invalid_request', 'Unsupported network operation', 400)
        self.access.validate_context(context)
        with Journal(self.store) as journal:
            flow = self._flow(journal); state = flow.state
            grant = self._grant(context, state, grant_id)
            self._check_cursor(journal, cursor)
            if operation != 'attest' and grant['kind'] != 'owner':
                raise CoreError('forbidden', 'Owner grant required for this operation', 403)
            if operation == 'attest':
                job = state['transport']['jobs'].get(args.get('job_id'))
                if job is None: raise CoreError('not_found', 'Unknown authorized job', 404)
                if args.get('role') not in self._attest_roles(grant, job):
                    raise CoreError('forbidden', 'Account cannot attest this handover role', 403)
            request_context = {'subject': context['subject'], 'grant': copy.deepcopy(grant),
                               'interface': INTERFACE, 'wire_sha256': digest(wire_bytes),
                               'transport_channel': transport_channel, 'operation': operation,
                               'owner_fence': None if operation == 'attest' else {
                                   'boot_id': args.get('boot_id'), 'assignment_epoch': args.get('assignment_epoch')}}
            _context(request_context)
            previous = state['transport']['requests'].get(request_id)
            # Read-only replay precedes boot/session fencing. A lost reply never
            # authorizes another effect, even after process restart or re-login.
            if previous is not None:
                if (previous.get('request_context') != request_context
                        or previous['principal'] != context['principal']):
                    raise CoreError('request_conflict', 'Request identity has different authenticated intent')
                return {'receipt': copy.deepcopy(previous), 'replayed': True,
                        'snapshot': self._snapshot(context, journal)}
            normalized = copy.deepcopy(args)
            if operation != 'attest': normalized = self._owner_fence(state, normalized)
            def guard():
                self._ensure_open()
                return self.access.validate_context(context)
            flow._authorization_guard = guard
            flow._service_boot_id = self.boot_id
            try:
                replayed = False
                if operation == 'resume':
                    domain.exact(normalized, '', 'owner resume arguments')
                    record, after, committed = flow.resume_network(context['principal'], request_id, args,
                        request_context, wire_bytes, self.boot_id, guard)
                    if committed:
                        with self._session_lock: self._write_session = after['session']
                    replayed = not committed
                else:
                    if (not self._write_session or state['session'] != self._write_session
                            or state['network']['boot_id'] != self.boot_id):
                        raise CoreError('owner_resume_required', 'Explicit owner resume is required for new effects')
                    if operation == 'attest':
                        domain.exact(normalized, 'job_id role observation_id assignment_epoch handover_id '
                                     'manifest_sha256 observed_rack_id confirmed', 'handover attestation')
                        domain.require(normalized['confirmed'] is True, 'Explicit complete-manifest confirmation required')
                        domain.ident(normalized['observed_rack_id']); domain.ident(normalized['handover_id'])
                        domain.checksum(normalized['manifest_sha256'])
                        envelope = domain.embedded_envelope(state['transport'], normalized['job_id'], flow._topology(state))
                        observation = domain.observation_for(envelope, normalized['role'], normalized['observation_id'])
                        observation.update({key: normalized[key] for key in
                                            ['assignment_epoch', 'handover_id', 'manifest_sha256']})
                        observation['rack_id'] = normalized['observed_rack_id']
                        internal, data = 'observe', {'job_id': normalized['job_id'], 'observation': observation}
                    elif operation == 'reconcile':
                        scope = normalized.pop('scope', None)
                        if scope == 'workflow': internal, data = 'workflow_reconcile', normalized
                        elif scope == 'job': internal, data = 'reconcile', normalized
                        else: raise CoreError('invalid_request', 'Explicit reconciliation scope required', 400)
                    else:
                        internal = 'mark_dispatched' if operation == 'dispatch' else operation
                        data = normalized
                    guard()
                    record, _, _ = flow._transport_transition(internal, context['principal'], request_id, data,
                                                              wire_bytes, request_context)
                    guard()
                return {'receipt': record, 'replayed': replayed, 'snapshot': self._snapshot(context, journal)}
            except CoreError:
                raise
            except TaskError as error:
                raise CoreError('workflow_rejected', 'Request was not committed; inspect current state and reconciliation requirements') from error
