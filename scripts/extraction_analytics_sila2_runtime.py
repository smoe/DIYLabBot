"""Existing DNA service's extraction feature over its same canonical journal."""
import copy
import json
import math
import threading
import uuid

import build_extraction_analytics_sila2 as contract
from extraction_analytics_demo import ACTOR
from extraction_analytics_sila2_control import MODE, NetworkExtractionAnalyticsWorkflow
from extraction_analytics_sila2_execution import ExecutionDriver
from extraction_analytics_workflow import ExtractionAnalyticsWorkflow
from extraction_analytics_stages import build_adapter
from dna_quantification_control import ExecutionInterrupted
from manual_tasks import Journal, TaskError, digest, encoded
from manual_workflow import text

RECONCILIATION = 'solidcraftbot.extraction-analytics-reconciliation/1'
PAUSES = {None, 'phase_intent', 'nanodrop_intent', 'qubit_preparation_intent', 'tapestation_loaded'}


class ExtractionAnalyticsRuntime:
    """A feature view; the host alone owns process identity, lock and storage."""
    def __init__(self, host_runtime, pause_after=None):
        if pause_after not in PAUSES: raise TaskError('Unsupported private extraction pause boundary')
        self.host = host_runtime
        self.profile = contract.load()
        self.pause_after = pause_after
        self.directory, self.journal_path = host_runtime.directory, host_runtime.journal_path
        self.server_uuid, self.boot_id = host_runtime.server_uuid, host_runtime.boot_id
        self.clock, self._mutex, self._closed = host_runtime.clock, host_runtime._mutex, host_runtime._closed
        self._sessions, self._cancellations = {}, {}

    @property
    def transport(self): return self.host.transport
    @transport.setter
    def transport(self, value): self.host.transport = value
    def close(self): pass  # Host lifetime owns the shared process lock.

    def _verify_pins(self): contract.verify_source_files(self.profile['source_files_sha256'])

    def _binding(self):
        return {'mode': MODE, 'server_uuid': self.server_uuid, 'source_files_sha256': self.profile['source_files_sha256']}

    def _normalize(self, name, arguments):
        definition = next((c for c in self.profile['commands'] if c['name'] == name), None)
        if definition is None or not isinstance(arguments, dict): raise TaskError('Unsupported extraction network command')
        if set(arguments) != {f['name'] for f in definition['arguments']}: raise TaskError('Exact extraction network arguments required')
        result = {}
        for field in definition['arguments']:
            value = arguments[field['name']]
            if field['type'].lower() in {'bool', 'boolean'}:
                if type(value) is not bool: raise TaskError('Boolean required: ' + field['name'])
            elif not isinstance(value, str): raise TaskError('String required: ' + field['name'])
            result[field['name']] = value
        for key in ('run_identifier', 'request_identifier'): text(result[key], key)
        if name == 'CreateRun' and result['family_identifier'] not in self.profile['families']:
            raise TaskError('Select the pinned dneasy or puregene family')
        return result

    def _belongs(self, state):
        return (state.get('format') == 'solidcraftbot.material-workflow-state/2'
            and state.get('definition', {}).get('profile', {}).get('type') == ExtractionAnalyticsWorkflow.ENGINE
            and state.get('control', {}).get('mode') == MODE
            and state.get('control', {}).get('server_uuid') == self.server_uuid)

    def _ids(self, journal):
        return [row[0] for row in journal.connection.execute('SELECT id FROM runs ORDER BY id')
                if self._belongs(journal.get_current(row[0])[0])]

    def _snapshot(self, journal, identity):
        state = journal.get_current(identity)[0]
        if not self._belongs(state): raise TaskError('An extraction network Root is required')
        return {'run_id': identity, 'root_status': state['status'], 'session': state['session'],
            'family': state['definition']['execution']['analytics']['family'],
            'active_device': state['analytics']['active_device'], 'pending_operation': state['pending_operation'],
            'phase_pending': state['process']['phase_pending'], 'resources': state['resources'],
            'recovery_required': state['recovery_required'], 'logical_time_s': state['logical_time_s'],
            'network_commands': state['network']['commands']}

    def status(self, run_identifier=''):
        result = {'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
            'simulation_only': True, 'hardware_available': False, 'ros_executed': False}
        with Journal(self.journal_path) as journal:
            ids = self._ids(journal); result.update(run_ids=ids, runs=[self._snapshot(journal, i) for i in ids])
            if run_identifier: result.update(self._snapshot(journal, run_identifier))
        return result

    def _report(self, journal, identity):
        state = journal.state(identity)[0]
        if not self._belongs(state): raise TaskError('An extraction network Root is required')
        report = ExtractionAnalyticsWorkflow(journal, identity, None).report()
        fields = ('sequence', 'kind', 'sha256', 'previous_sha256', 'time_unix_s')
        report['trace'] = [{key: copy.deepcopy(event[key]) for key in fields} for event in report['trace']]
        report['wire_projection'] = {'format': 'solidcraftbot.extraction-analytics-sila2-wire-report/1',
            'trace': 'metadata_only', 'full_journal': 'private canonical Root journal'}
        report['transport_receipts'] = {'control': state['control'], 'network': state['network'],
            'sila_loopback_executed': any(r['transport'] == 'sila2_tls_loopback' for r in state['network']['commands'].values()),
            'scope': 'synthetic Root control only; no instrument communication'}
        return report

    def report(self, run_identifier=''):
        with Journal(self.journal_path) as journal:
            if run_identifier: return self._report(journal, run_identifier)
            return {'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
                'reports': {i: self._report(journal, i) for i in self._ids(journal)}}

    def cancel_execution(self, execution_uuid, principal=None, guard=None):
        if guard: guard()
        entry = self._cancellations.get(execution_uuid)
        if entry is None: raise TaskError('Unknown active extraction execution')
        if principal is not None and entry[0] != principal: raise PermissionError('Execution belongs to another principal')
        entry[1].set()
        return {'execution_uuid': execution_uuid, 'cancel_requested': True, 'root_cancelled': False, 'resources_released': False}

    @staticmethod
    def _previous(state, request, fingerprint, principal):
        previous = state.get('network', {}).get('commands', {}).get(request)
        if previous is None: return None
        if previous['fingerprint'] != fingerprint or previous['principal'] != principal:
            raise TaskError('Request identifier reused with different arguments or principal')
        return copy.deepcopy(previous.get('response') or {'run_id': state['run_id'], 'request_id': request,
            'command': previous['command'], 'execution_uuid': previous['execution_uuid'],
            'outcome': previous['status'], 'root_status': state['status'], 'error': previous.get('error')})

    def command(self, name, arguments, principal, execution_uuid=None, guard=None):
        self._verify_pins(); args = self._normalize(name, arguments); text(principal, 'network principal')
        request, identity = args['request_identifier'], args['run_identifier']
        fingerprint = digest(encoded({'command': name, 'arguments': args}).encode())
        execution_uuid = execution_uuid or str(uuid.uuid4())
        cancelled = threading.Event(); self._cancellations[execution_uuid] = (principal, cancelled)

        def boundary():
            self._verify_pins()
            if guard: guard()
            if cancelled.is_set() or self._closed.is_set(): raise ExecutionInterrupted('CommandCanceled')

        try:
            if guard: guard()
            # A durable receipt remains readable while the worker owns the mutex.
            with Journal(self.journal_path) as reader:
                if reader.connection.execute('SELECT 1 FROM runs WHERE id=?', (identity,)).fetchone():
                    state = reader.state(identity)[0]
                    if state.get('control') != self._binding(): raise TaskError('Run belongs to another feature/server/source revision')
                    previous = self._previous(state, request, fingerprint, principal)
                    if previous is not None: return previous
            with self._mutex, Journal(self.journal_path) as journal:
                boundary()
                found = journal.connection.execute('SELECT 1 FROM runs WHERE id=?', (identity,)).fetchone()
                before = journal.state(identity)[0] if found else None
                if before:
                    if before.get('control') != self._binding() or not self._belongs(before):
                        raise TaskError('Run belongs to another feature/server/source revision')
                    previous = self._previous(before, request, fingerprint, principal)
                    if previous is not None: return previous
                    if name == 'CreateRun': raise TaskError('Run identifier already exists')
                    if before['status'] in {'completed', 'cancelled'} and name != 'ResumeRun':
                        raise TaskError('Terminal Root: read its report, replay the original request or explicitly resume receipt metadata')
                    if name != 'ResumeRun' and (before['network']['boot_id'] != self.boot_id or self._sessions.get(identity) != before['session']):
                        raise TaskError('Explicit ResumeRun and reconciliation required')
                elif name != 'CreateRun': raise TaskError('Create the explicitly identified extraction run first')
                context = {'request_id': request, 'fingerprint': fingerprint, 'command': name, 'arguments': args,
                    'principal': principal, 'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
                    'execution_uuid': execution_uuid, 'clock': self.clock, 'transport': self.transport}
                if before is None:
                    source = contract.ROOT / self.profile['families'][args['family_identifier']]['source']
                    flow = NetworkExtractionAnalyticsWorkflow.create(journal, source, identity, control=self._binding(),
                        command_context=context, transition_guard=boundary, actor_id=ACTOR)
                    self._sessions[identity] = flow.session
                else:
                    flow = NetworkExtractionAnalyticsWorkflow(journal, identity, self._sessions.get(identity),
                        command_context=context, transition_guard=boundary)
                try:
                    if name == 'ResumeRun':
                        flow = NetworkExtractionAnalyticsWorkflow.open(journal, identity, resume=args['resume'],
                            control=self._binding(), command_context=context, transition_guard=boundary)
                        self._sessions[identity] = flow.session
                    elif name == 'RunUntilDecision': ExecutionDriver(flow, self._pause).run()
                    elif name in {'ReconcileRun', 'FinishCancel'}: self._reconcile(flow, args['observation_json'], finish=name == 'FinishCancel')
                    elif name == 'CancelRun': flow.act('cancel', ACTOR, reason=args['reason'])
                    response = {'run_id': identity, 'request_id': request, 'command': name, 'execution_uuid': execution_uuid,
                        'outcome': 'completed', 'root_status': flow.state['status'], 'error': None}
                    flow.finish_command(response); return response
                except (TaskError, PermissionError, ValueError, TypeError) as error:
                    state = flow.state; own = state.get('network', {}).get('commands', {}).get(request)
                    if own is None: raise
                    interrupted = isinstance(error, (ExecutionInterrupted, PermissionError))
                    code = ('RecoveryRequired' if flow._pending(state) else 'CommandCanceled') if interrupted else 'WorkflowRejected'
                    if interrupted and state['status'] not in {'completed', 'cancelled'}:
                        flow.control_event('execution_interrupted', lambda s: s.update(
                            recovery_required=s['recovery_required'] or 'execution_interrupted', workspace_clear=False),
                            {'error': code}, trusted=True)
                    response = {'run_id': identity, 'request_id': request, 'command': name, 'execution_uuid': execution_uuid,
                        'outcome': 'interrupted' if interrupted else 'failed', 'root_status': flow.state['status'],
                        'error': code, 'message': str(error)}
                    flow.finish_command(response, outcome=response['outcome'], error=code); return response
        finally: self._cancellations.pop(execution_uuid, None)

    def _pause(self, point, flow):
        if self.pause_after == point:
            while not self._closed.wait(0.05): flow.transition_guard()
            raise ExecutionInterrupted('Server stopped at private extraction test boundary')

    @staticmethod
    def _document(raw):
        if not isinstance(raw, str) or len(raw.encode()) > 262144: raise TaskError('Bounded explicit reconciliation JSON required')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result: raise TaskError('Duplicate reconciliation field')
                result[key] = value
            return result
        def constant(value): raise TaskError('Finite reconciliation values required')
        try:
            data = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        except (ValueError, RecursionError) as error:
            raise TaskError('Malformed or excessively nested reconciliation JSON') from error
        pending = [(data, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 32: raise TaskError('Reconciliation JSON nesting exceeds its bound')
            if isinstance(value, float) and not math.isfinite(value): raise TaskError('Finite reconciliation numbers required')
            if isinstance(value, dict): pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list): pending.extend((item, depth + 1) for item in value)
        required = {'format', 'reason', 'observations', 'workspace_clear'}
        optional = {'extraction', 'device', 'tapestation_abort', 'dispositions', 'vessel_disposals'}
        if (not isinstance(data, dict) or not required <= set(data) or set(data) - required - optional
                or data['format'] != RECONCILIATION or type(data['workspace_clear']) is not bool
                or not isinstance(data['observations'], list)):
            raise TaskError('Exact versioned reconciliation document required')
        text(data['reason'], 'reconciliation reason')
        for name in ('extraction', 'device', 'tapestation_abort'):
            if name in data and data[name] is not None and not isinstance(data[name], dict): raise TaskError('Explicit reconciliation object or null required: ' + name)
        for name in ('dispositions', 'vessel_disposals'):
            if name in data and not isinstance(data[name], list): raise TaskError('Explicit reconciliation list required: ' + name)
        if data.get('extraction') and data.get('device'): raise TaskError('Only one pending-effect resolution is permitted')
        return data

    def _reconcile(self, flow, raw, *, finish=False):
        data = self._document(raw)
        if not data['workspace_clear']: raise TaskError('Explicit workspace clearance observation required')
        if finish and flow.state['status'] != 'cancelling': raise TaskError('CancelRun is required before FinishCancel')
        if not finish and (data.get('dispositions') or data.get('vessel_disposals')):
            raise TaskError('Only FinishCancel accepts dispositions')
        def update(state): self._apply_document(flow, state, data, finish)
        return flow.control_event('network_reconciliation', update,
            {'document_format': data['format'], 'reason': data['reason'], 'no_effect_replayed': True})

    @staticmethod
    def _apply_document(flow, state, data, finish):
        extraction, device = data.get('extraction'), data.get('device')
        active = state['analytics']['active_device']
        if device is not None:
            if set(device) != {'device', 'pending_resolution', 'device_valid', 'reason'} or device['device'] != active:
                raise TaskError('Exact active device reconciliation required')
            flow._resolve_device(state, ACTOR, **device)
        elif active:
            raise TaskError('Explicit active-device validity and pending outcome required')
        if extraction is not None:
            if not {'intent_id', 'outcome', 'reason'} <= set(extraction) or set(extraction) - {
                    'intent_id', 'outcome', 'reason', 'actual_inputs', 'actual_outputs', 'observations'}:
                raise TaskError('Exact extraction pending-effect resolution required')
            flow._resolve_effect(state, ACTOR, **extraction)
        elif state['process']['phase_pending'] is not None:
            raise TaskError('Explicit extraction pending-effect resolution required')
        selected = extraction or (device or {}).get('pending_resolution')
        if selected and selected.get('outcome') == 'unknown':
            if finish: raise TaskError('Unknown effects cannot release resources')
            flow._inventory(state, data['observations'], ACTOR)
            return
        if flow._pending(state): raise TaskError('Resolve every pending effect explicitly')
        abort = data.get('tapestation_abort')
        if abort is not None:
            if set(abort) != {'observations', 'reason'}: raise TaskError('Exact TapeStation abort observations required')
            observed = abort['observations']
            if not isinstance(observed, dict): raise TaskError('Exact TapeStation abort observation object required')
            flags = ('instrument_stopped', 'sample_retrieved', 'ladder_retrieved', 'materials_accounted', 'identities_confirmed')
            if any(observed.get(flag) is not True for flag in flags):
                raise TaskError('TapeStation abort confirmations must be literal true booleans')
            request = state['process']['qc']['request']
            if request is None: raise TaskError('No TapeStation request exists to abort')
            expected = flow._abort_identities(request)
            for key, value in expected.items():
                if type(value) in (int, bool) and type(observed.get(key)) is not type(value):
                    raise TaskError('TapeStation abort identity type differs: ' + key)
            flow._confirm_tapestation_abort(state, ACTOR, **abort)
        if finish:
            for row in data.get('vessel_disposals', []):
                if not isinstance(row, dict) or set(row) != {'vessel_id', 'reason'} or active != 'qubit':
                    raise TaskError('Only explicit existing Qubit tube disposals are supported')
                build_adapter(flow, state, 'qubit')._dispose_vessel(
                    build_adapter(flow, state, 'qubit').state, ACTOR,
                    row['vessel_id'], row['vessel_id'], row['reason'])
            live = {identity for identity, m in state['inventory']['materials'].items() if m['disposition'] not in {'consumed', 'discarded'}}
            rows = data.get('dispositions', [])
            if len(rows) != len(live) or {r.get('material_id') for r in rows if isinstance(r, dict)} != live:
                raise TaskError('Complete explicit final material dispositions required')
            for row in rows:
                if set(row) != {'material_id', 'disposition', 'reason'} or row['disposition'] not in {'retained', 'discarded', 'quarantined'}:
                    raise TaskError('Exact explicit final material disposition required')
                flow._set_disposition(state, ACTOR, **row)
        if state['status'] == 'created': flow._accept_inventory(state, ACTOR, data['observations'])
        if state['recovery_required']:
            flow._reconcile(state, ACTOR, data['observations'], True, reason=data['reason'])
        else: flow._confirm_inventory(state, ACTOR, data['observations'])
        if finish:
            spec = state['definition']['execution']['analytics']
            if state['inventory']['vessels'][spec['product_vessel_id']]['location'] != spec['product_home']:
                raise TaskError('FinishCancel requires original product-vessel return')
            if spec['product_material_id'] in state['inventory']['materials'] and state['inventory']['materials'][spec['product_material_id']]['disposition'] not in {'retained', 'quarantined'}:
                raise TaskError('Retain or quarantine the identified DNA product on cancellation')
            flow._confirm_inventory(state, ACTOR, data['observations'])
            flow._finish_cancel(state, ACTOR, workspace_clear=True)
