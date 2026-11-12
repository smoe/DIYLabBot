"""Serialized SiLA execution over the existing DNA root's atomic journal.

Only identity and an exclusive process lock live outside that journal. There
is no transport database or independent stock/operation state machine.
"""
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid

from manual_tasks import Journal, TaskError, encoded, digest
from manual_workflow import ROOT, text
from dna_quantification import Workflow
from dna_quantification_control import ExecutionInterrupted
from dna_quantification_port import interface_generated
from dna_quantification_demo import SyntheticBackend, run_synthetic
import build_dna_quantification_sila2 as contract


class DNARuntime:
    def __init__(self, directory, server_uuid=None, boot_id=None, clock=time.time, pause_after=None):
        self.directory = Path(directory).resolve()
        if not self.directory.is_relative_to(ROOT / 'exports'):
            raise TaskError('Private DNA server data must stay under this worktree exports/')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock_file = (self.directory / 'server.lock').open('a+b')
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._lock_file.close()
            raise TaskError('Another DNA server owns this private runtime directory') from error
        try:
            self.profile = contract.load()
            identity = self.directory / 'identity.json'
            if identity.exists():
                stored = json.loads(identity.read_text())
                self.server_uuid = str(uuid.UUID(stored['server_uuid']))
                if server_uuid is not None and server_uuid != self.server_uuid:
                    raise TaskError('Persistent DNA server identity mismatch')
            else:
                self.server_uuid = str(uuid.UUID(server_uuid)) if server_uuid else str(uuid.uuid4())
                descriptor = os.open(identity, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'w') as output:
                    output.write(encoded({'server_uuid': self.server_uuid}) + '\n')
                    output.flush(); os.fsync(output.fileno())
            self.boot_id = str(uuid.UUID(boot_id)) if boot_id else str(uuid.uuid4())
            self.clock, self.pause_after = clock, pause_after
            self.transport = 'in_process'
            self.journal_path = self.directory / 'workflows.sqlite3'
            self.actor_id = 'SYN.DNA.Operator01'
            self._mutex = threading.RLock()
            self._sessions, self._cancellations = {}, {}
            self._closed = threading.Event()
            with Journal(self.journal_path):
                pass
        except BaseException:
            self._lock_file.close()
            raise

    def close(self):
        self._closed.set()
        self._lock_file.close()

    def _normalize(self, name, arguments):
        definition = next((c for c in self.profile['commands'] if c['name'] == name), None)
        if definition is None or not isinstance(arguments, dict):
            raise TaskError('Unsupported DNA network command')
        fields = definition['arguments']
        if set(arguments) != {field['name'] for field in fields}:
            raise TaskError('Exact declared DNA network arguments required')
        result = {}
        for field in fields:
            key = field['name']; value = arguments[key]; kind = field['type'].lower()
            if kind in {'string'}:
                if not isinstance(value, str): raise TaskError('String required: ' + key)
            elif kind in {'bool', 'boolean'}:
                if type(value) is not bool: raise TaskError('Boolean required: ' + key)
            elif kind in {'real', 'number', 'float64'}:
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise TaskError('Finite number required: ' + key)
                value = float(value)
            else:
                raise TaskError('Unsupported network primitive')
            result[key] = value
        text(result['request_identifier'], 'request identifier')
        text(result['run_identifier'], 'run identifier')
        return result

    def _binding(self):
        return {'mode': 'sila2_network/1', 'server_uuid': self.server_uuid,
                'source_files_sha256': self.profile['source_files_sha256']}

    @staticmethod
    def _pending(state):
        if state.get('task_port', {}).get('pending_goal_id'): return True
        if state['pending_dilution']: return True
        if state['active_context_id']:
            local = state['contexts'][state['active_context_id']]['local']
            return bool(local.get('pending_measurement') or local.get('pending_operation'))
        return False

    def _snapshot(self, journal, run_id):
        state, _ = journal.get_current(run_id)
        return {'run_id': run_id, 'root_status': state['status'],
                'active_attempt_id': state['active_attempt_id'], 'active_context_id': state['active_context_id'],
                'recovery_required': state['recovery_required'], 'cancel_requested': state['cancel_requested'],
                'logical_time_s': state['logical_time_s'], 'resources': state['resources'],
                'network_commands': state.get('network', {}).get('commands', {})}

    def status(self, run_identifier=''):
        result = {'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
                  'simulation_only': True, 'hardware_available': False,
                  'ros_interface_generated': interface_generated(),
                  'ros_compiled': False, 'ros_executed': False}
        with Journal(self.journal_path) as journal:
            ids = [row[0] for row in journal.connection.execute('SELECT id FROM runs ORDER BY id')]
            result['run_ids'] = ids
            if run_identifier:
                result.update(self._snapshot(journal, run_identifier))
            else:
                result['runs'] = [self._snapshot(journal, identity) for identity in ids]
        return result

    def report(self, run_identifier=''):
        with Journal(self.journal_path) as journal:
            if not run_identifier:
                ids = [r[0] for r in journal.connection.execute('SELECT id FROM runs ORDER BY id')]
                return {'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
                        'reports': {identity: Workflow(journal, identity).report() for identity in ids}}
            return Workflow(journal, run_identifier).report()

    def cancel_execution(self, execution_uuid, principal=None, guard=None):
        if guard: guard()
        entry = self._cancellations.get(execution_uuid)
        if entry is None: raise TaskError('Unknown active DNA execution')
        if principal is not None and entry[0] != principal:
            raise PermissionError('Execution belongs to another principal')
        entry[1].set()
        return {'execution_uuid': execution_uuid, 'cancel_requested': True,
                'root_cancelled': False, 'resources_released': False}

    def command(self, name, arguments, principal, execution_uuid=None, guard=None):
        args = self._normalize(name, arguments)
        text(principal, 'network principal')
        request_id, run_id = args['request_identifier'], args['run_identifier']
        fingerprint = digest(encoded({'command': name, 'arguments': args}).encode())
        execution_uuid = execution_uuid or str(uuid.uuid4())
        cancellation = threading.Event()
        self._cancellations[execution_uuid] = (principal, cancellation)

        def boundary():
            if guard: guard()
            if cancellation.is_set() or self._closed.is_set():
                raise ExecutionInterrupted('CommandCanceled')

        try:
            with self._mutex, Journal(self.journal_path) as journal:
                if guard: guard()
                exists = journal.connection.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone()
                before = journal.get_current(run_id)[0] if exists else None
                if before:
                    if before.get('control', {}).get('server_uuid') != self.server_uuid:
                        raise TaskError('Run is not bound to this DNA server')
                    previous = before['network']['commands'].get(request_id)
                    if previous:
                        if previous['fingerprint'] != fingerprint or previous['principal'] != principal:
                            raise TaskError('Request identifier was already used with different arguments/principal')
                        # All returns are stored observations, never redispatch.
                        return copy.deepcopy(previous['response'] or {
                            'run_id': run_id, 'request_id': request_id, 'command': previous['command'],
                            'execution_uuid': previous['execution_uuid'], 'outcome': previous['status'],
                            'error': previous.get('error'), 'root_status': before['status']})
                elif name != 'CreateRun':
                    raise TaskError('Create the explicitly identified run first')
                context = {'request_id': request_id, 'fingerprint': fingerprint,
                    'command': name, 'arguments': args, 'principal': principal,
                    'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
                    'execution_uuid': execution_uuid, 'clock': self.clock,
                    'transport': self.transport, 'evidence': 'synthetic_backend'}
                if name in {'ReconcileInventory', 'FinishCancel', 'AcceptResult', 'CancelRun', 'ChooseDilution'}:
                    context['evidence'] = 'synthetic_person_input'
                if not before:
                    boundary()
                    flow = Workflow.create(journal, run_id=run_id, control=self._binding(),
                        command_context=context, transition_guard=boundary,
                        responsible_person_id=self.actor_id)
                    self._sessions[run_id] = flow.session
                else:
                    if name == 'CreateRun': raise TaskError('Run identifier already exists')
                    flow = Workflow(journal, run_id, self._sessions.get(run_id), context, boundary)
                    if name == 'ResumeRun':
                        if not args['resume'] and before['session'] is not None:
                            raise TaskError('Explicit resume required for an open previous session')
                        flow.session = uuid.uuid4().hex
                        self._sessions[run_id] = flow.session
                    elif (before['network']['boot_id'] != self.boot_id
                          or (before['status'] not in {'completed', 'cancelled'}
                              and flow.session != before['session'])):
                        raise TaskError('ResumeRun and explicit inventory reconciliation required')
                try:
                    if name == 'CreateRun':
                        pass
                    elif name == 'ResumeRun':
                        flow.resume_network(self.actor_id)
                    elif name == 'RunUntilDecision':
                        self._run(flow, args)
                    elif name == 'ChooseDilution':
                        flow.choose_dilution(self.actor_id, args['sample_identifier'], args['dilution_preset'])
                    elif name == 'AcceptResult':
                        flow.accept_result(self.actor_id, args['sample_identifier'],
                            allow_unquantified=args['allow_unquantified'], reason=args['reason'])
                    elif name == 'ReconcileInventory':
                        data = json.loads(args['observation_json'])
                        if not isinstance(data, dict): raise TaskError('Explicit inventory observation object required')
                        flow.reconcile(self.actor_id, **data)
                    elif name == 'CancelRun':
                        flow.cancel(self.actor_id, args['reason'])
                    elif name == 'FinishCancel':
                        data = json.loads(args['observation_json'])
                        if not isinstance(data, dict): raise TaskError('Explicit cancellation observation object required')
                        flow.finish_cancel(self.actor_id, **data)
                    state = flow.state
                    response = {'run_id': run_id, 'request_id': request_id, 'command': name,
                        'execution_uuid': execution_uuid, 'outcome': 'completed',
                        'root_status': state['status'], 'error': None}
                    flow.finish_command(self.actor_id, response)
                    return response
                except (TaskError, PermissionError, TypeError, ValueError) as error:
                    # Only interrupted commands need a held root. A rejected
                    # request never undoes an earlier committed withdrawal.
                    state = flow.state
                    own = state.get('network', {}).get('commands', {}).get(request_id)
                    if own is None:
                        raise
                    interrupted = isinstance(error, (ExecutionInterrupted, PermissionError))
                    code = ('ReconciliationRequired' if self._pending(state) else 'CommandCanceled') if interrupted else type(error).__name__
                    if interrupted and state['status'] not in {'completed', 'cancelled'}:
                        def hold(current):
                            current['status'] = 'cancelling' if current['cancel_requested'] else 'held'
                            current['recovery_required'] = current['recovery_required'] or 'execution_interrupted'
                        flow.control_event('execution_interrupted', self.actor_id, hold,
                                           {'error': code})
                    response = {'run_id': run_id, 'request_id': request_id, 'command': name,
                        'execution_uuid': execution_uuid, 'outcome': 'interrupted' if interrupted else 'failed',
                        'root_status': flow.state['status'], 'error': code, 'message': str(error)}
                    flow.finish_command(self.actor_id, response, outcome=response['outcome'], error=code)
                    return response
        finally:
            self._cancellations.pop(execution_uuid, None)

    def _run(self, flow, args):
        scenario = {key: args[key] for key in ['nanodrop_concentration', 'qubit_concentration', 'qubit_report_original']}
        SyntheticBackend({'nanodrop': scenario['nanodrop_concentration'], 'qubit': scenario['qubit_concentration']},
                         qubit_report_original=scenario['qubit_report_original'])
        state = flow.state
        stored = state.get('scenario')
        if stored is not None and stored != scenario:
            raise TaskError('Synthetic scenario is bound to this run; do not replace its fictitious values')
        if stored is None:
            flow.control_event('scenario_bound', self.actor_id,
                lambda current: current.update(scenario=copy.deepcopy(scenario)),
                {'scenario': scenario})
        from dna_quantification_execution import NetworkSyntheticBackend
        backend = NetworkSyntheticBackend({'nanodrop': scenario['nanodrop_concentration'], 'qubit': scenario['qubit_concentration']},
            qubit_report_original=scenario['qubit_report_original'], actor_id=self.actor_id)
        # A caller-chosen dilution persisted in an earlier command is an intent,
        # not an automatically performed transfer. The network synthetic worker
        # may confirm only a same-boot, never-dispatched selection after checking
        # that no recovery is pending. Restarted intents require person input.
        state = flow.state
        if state['pending_dilution'] and not state['recovery_required']:
            backend.confirm_dilution(flow)
        run_synthetic(flow, args['initial_dilution'], args['after_range'] or None,
                      backend, self.pause_after)
        if self.pause_after and self._pending(flow.state):
            while not self._closed.wait(0.05):
                flow.transition_guard()
            raise ExecutionInterrupted('Server stopped at injected intent boundary')
