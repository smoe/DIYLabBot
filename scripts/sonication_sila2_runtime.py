"""SiLA command coordinator for the existing test-only CUT&RUN S09 root.

Only TLS identity and a process lock live outside the canonical root journal.
The fixture backend never observes hardware and never automatically reconciles
an uncertain effect from its own inventory projection.
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

import build_cutrun_input_sonication_sila2 as contract
from cutrun_input_sonication_control import NetworkInputSonicationWorkflow, ExecutionInterrupted
from cutrun_input_sonication_demo import FixtureClock, FixtureSession, fixture_values, validate_run_id
from cutrun_input_sonication_workflow import InputSonicationWorkflow
from manual_tasks import Journal, TaskError, digest, encoded
from manual_workflow import ROOT, text
import material_ledger as ledger

RECONCILIATION = 'solidcraftbot.s09-fixture-reconciliation/1'


class SonicationRuntime:
    def __init__(self, directory, server_uuid=None, boot_id=None, clock=time.time, pause_after=None):
        self.directory = Path(directory).resolve()
        if not self.directory.is_relative_to(ROOT / 'exports'):
            raise TaskError('Private sonication data must stay under this worktree exports/')
        if pause_after not in {None, 'sonication_intent', 'sonication_confirmed',
                'opening_complete', 'input_preparation_intent', 'phase_time',
                'qc_withdrawal_intent', 'qc_confirmed'}:
            raise TaskError('Unsupported private sonication fault-injection boundary')
        # Validate all pins before creating a store, identity or resource hold.
        self.profile = contract.load()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock_file = (self.directory / 'server.lock').open('a+b')
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._lock_file.close()
            raise TaskError('Another server owns this sonication runtime directory') from error
        try:
            identity = self.directory / 'identity.json'
            if identity.exists():
                self.server_uuid = str(uuid.UUID(json.loads(identity.read_text())['server_uuid']))
                if server_uuid is not None and server_uuid != self.server_uuid:
                    raise TaskError('Persistent sonication server identity mismatch')
            else:
                self.server_uuid = str(uuid.UUID(server_uuid)) if server_uuid else str(uuid.uuid4())
                fd = os.open(identity, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(encoded({'server_uuid': self.server_uuid}) + '\n')
                    stream.flush(); os.fsync(stream.fileno())
            self.boot_id = str(uuid.UUID(boot_id)) if boot_id else str(uuid.uuid4())
            self.clock, self.pause_after = clock, pause_after
            self.transport = 'in_process'
            self.journal_path = self.directory / 'workflows.sqlite3'
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

    def _verify_pins(self):
        contract.verify_source_files(self.profile['source_files_sha256'])

    def _normalize(self, name, arguments):
        definition = next((item for item in self.profile['commands'] if item['name'] == name), None)
        if definition is None or not isinstance(arguments, dict):
            raise TaskError('Unsupported sonication network command')
        if set(arguments) != {field['name'] for field in definition['arguments']}:
            raise TaskError('Exact declared sonication network arguments required')
        result = {}
        for field in definition['arguments']:
            key, kind = field['name'], field['type']
            value = arguments[key]
            if ((kind == 'string' and not isinstance(value, str))
                    or (kind == 'bool' and type(value) is not bool)):
                raise TaskError('Invalid network argument: ' + key)
            result[key] = value
        validate_run_id(result['run_identifier'])
        text(result['request_identifier'], 'request identifier')
        if name == 'CreateRun' and result['scenario_identifier'] not in fixture_values()['scenarios']:
            raise TaskError('Choose an explicitly pinned fixture scenario')
        return result

    def _binding(self):
        return {'mode': 's09_sila2_network/1', 'server_uuid': self.server_uuid,
                'source_files_sha256': self.profile['source_files_sha256']}

    @staticmethod
    def _scenario(state):
        records = state['network']['commands'].values()
        return next(record['arguments']['scenario_identifier'] for record in records
                    if record['command'] == 'CreateRun')

    def _fixture(self, journal, run_id, context, boundary, *, create=False):
        if create:
            fixture = FixtureSession(journal, run_id, self.directory / 'fixtures' / run_id,
                context['arguments']['scenario_identifier'], workflow_class=NetworkInputSonicationWorkflow,
                workflow_options={'control': self._binding(), 'command_context': context,
                                  'transition_guard': boundary}, reuse_fixture_evidence=True,
                initialize_fixture=False)
            self._sessions[run_id] = fixture.flow.session
            return fixture
        state = journal.state(run_id)[0]
        values = fixture_values(); scenario = values['scenarios'][self._scenario(state)]
        fixture = object.__new__(FixtureSession)
        fixture.journal, fixture.run_id = journal, run_id
        fixture.directory = self.directory / 'fixtures' / run_id
        fixture.fixture, fixture.prefix, fixture.actor = values, scenario['prefix'], values['actor_id']
        fixture.reaction_id = fixture.prefix + '.Reaction.Input'
        fixture.vessel_id, fixture.device_id = fixture.prefix + '.input.Tube', fixture.prefix + '.Sonicator'
        fixture.origin_location = {'kind': 'rack', 'rack_id': fixture.prefix + '.Rack', 'place_id': 'P07'}
        fixture.stage_run_id, fixture.intent_id = fixture.prefix + '.Stage.S09', fixture.prefix + '.Sonication'
        fixture.output_material_id = fixture.prefix + '.FragmentedInput'
        fixture.time_basis = scenario['clock_id']
        fixture.clock = FixtureClock(record=copy.deepcopy(state['clock']['last_sample']))
        fixture._started_ns, fixture._samples, fixture._last_sequence = time.perf_counter_ns(), [], 0
        fixture.serial = max([int(name.rsplit('.', 1)[1]) for name in state['manual']['observations']
                             if name.startswith(fixture.prefix + '.Observation.')] or [0])
        stage = state['sop']['stages'].get(fixture.stage_run_id)
        fixture.phase_started_s = 0 if stage is None else stage['started_at']['monotonic_ns'] / 1_000_000_000
        fixture.materials, fixture.vessels, fixture.reactions = fixture._declarations()
        fixture.evidence_files = {'decision_evidence': fixture.directory / (run_id + '.fixture-decisions.json')}
        fixture.source = fixture._source()
        fixture.flow = NetworkInputSonicationWorkflow(journal, run_id, self._sessions.get(run_id),
            clock=fixture.clock, command_context=context, transition_guard=boundary)
        return fixture

    @staticmethod
    def _snapshot(journal, run_id):
        state = journal.state(run_id)[0]
        identity = state['definition']['runtime_profile']['bindings']['input_reaction_id']
        material = state['manual']['reactions'][identity]['current_material_id']
        stages = [stage for stage in state['sop']['stages'].values() if stage['stage_id'] == 'S09']
        return {'run_id': run_id, 'root_status': state['status'], 'session': state['session'],
                'resources': state['resources'], 'pending_operation': state['pending_operation'],
                'recovery_required': state['recovery_required'], 'clock': state['clock'],
                'network_commands': state['network']['commands'], 's09_stages': stages,
                'material_id': material, 'vessel_id': state['manual']['reactions'][identity]['vessel_id'],
                'remaining': ledger.remaining(state, material)}

    def status(self, run_identifier=''):
        result = {'server_uuid': self.server_uuid, 'boot_id': self.boot_id, 'simulation_only': True,
                  'hardware_available': False, 'ros_executed': False, 'hardware_executed': False}
        with Journal(self.journal_path) as journal:
            ids = [row[0] for row in journal.connection.execute('SELECT id FROM runs ORDER BY id')]
            result.update(run_ids=ids, runs=[self._snapshot(journal, identity) for identity in ids])
            if run_identifier:result.update(self._snapshot(journal, run_identifier))
        return result

    def report(self, run_identifier=''):
        with Journal(self.journal_path) as journal:
            if not run_identifier:
                ids = [row[0] for row in journal.connection.execute('SELECT id FROM runs ORDER BY id')]
                return {'server_uuid': self.server_uuid, 'boot_id': self.boot_id,
                        'reports': {identity: self._report(journal, identity) for identity in ids}}
            return self._report(journal, run_identifier)

    def _report(self, journal, run_id):
        result = InputSonicationWorkflow(journal, run_id, None).report()
        state = journal.state(run_id)[0]
        reaction_id = state['definition']['runtime_profile']['bindings']['input_reaction_id']
        vessel_id = state['manual']['reactions'][reaction_id]['vessel_id']
        result['transport_receipts'] = {'control': state['control'], 'network': state['network'],
            'fixture_context': {'input_reaction_id': reaction_id, 'vessel_id': vessel_id,
                                'original_rack_location': InputSonicationWorkflow._origin(state, vessel_id)},
            'scope': 'synthetic root control only; no instrument communication',
            'sila_loopback_executed': any(record['transport'] == 'sila2_loopback'
                                          for record in state['network']['commands'].values())}
        return result

    def cancel_execution(self, execution_uuid, principal=None, guard=None):
        if guard:guard()
        entry = self._cancellations.get(execution_uuid)
        if entry is None:raise TaskError('Unknown active sonication execution')
        if principal is not None and entry[0] != principal:
            raise PermissionError('Execution belongs to another principal')
        entry[1].set()
        return {'execution_uuid': execution_uuid, 'cancel_requested': True,
                'root_cancelled': False, 'resources_released': False}

    def command(self, name, arguments, principal, execution_uuid=None, guard=None):
        self._verify_pins()
        args = self._normalize(name, arguments)
        text(principal, 'network principal')
        run_id, request_id = args['run_identifier'], args['request_identifier']
        fingerprint = digest(encoded({'command': name, 'arguments': args}).encode())
        execution_uuid = execution_uuid or str(uuid.uuid4())
        cancellation = threading.Event()
        self._cancellations[execution_uuid] = (principal, cancellation)

        def boundary():
            self._verify_pins()
            if guard:guard()
            if cancellation.is_set() or self._closed.is_set():
                raise ExecutionInterrupted('CommandCanceled')

        try:
            # Reconnect/retry must be able to read an already durable receipt
            # while its first execution is waiting at a process-test boundary.
            if guard:guard()
            with Journal(self.journal_path) as reader:
                found = reader.connection.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone()
                if found:
                    state = reader.state(run_id)[0]
                    previous = state.get('network', {}).get('commands', {}).get(request_id)
                    if previous is not None:
                        if state.get('control') != self._binding() or previous['fingerprint'] != fingerprint or previous['principal'] != principal:
                            raise TaskError('Request identifier reused with different binding/arguments/principal')
                        return copy.deepcopy(previous.get('response') or {
                            'run_id': run_id, 'request_id': request_id, 'command': previous['command'],
                            'execution_uuid': previous['execution_uuid'], 'outcome': previous['status'],
                            'root_status': state['status'], 'error': previous.get('error')})
            with self._mutex, Journal(self.journal_path) as journal:
                boundary()
                exists = journal.connection.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone()
                before = journal.state(run_id)[0] if exists else None
                if before:
                    if before.get('control') != self._binding():
                        raise TaskError('Run belongs to another server or pinned source revision')
                    previous = before['network']['commands'].get(request_id)
                    if previous:
                        if previous['fingerprint'] != fingerprint or previous['principal'] != principal:
                            raise TaskError('Request identifier reused with different arguments/principal')
                        return copy.deepcopy(previous.get('response') or {
                            'run_id': run_id, 'request_id': request_id, 'command': previous['command'],
                            'execution_uuid': previous['execution_uuid'], 'outcome': previous['status'],
                            'root_status': before['status'], 'error': previous.get('error')})
                    if name == 'CreateRun':raise TaskError('Run identifier already exists')
                    if name != 'ResumeRun' and (before['network']['boot_id'] != self.boot_id
                            or self._sessions.get(run_id) != before['session']):
                        raise TaskError('Explicit ResumeRun and reconciliation required')
                elif name != 'CreateRun':
                    raise TaskError('Create the explicitly identified fixture run first')
                context = {'request_id': request_id, 'fingerprint': fingerprint, 'command': name,
                    'arguments': args, 'principal': principal, 'server_uuid': self.server_uuid,
                    'boot_id': self.boot_id, 'execution_uuid': execution_uuid,
                    'clock': self.clock, 'transport': self.transport}
                fixture = self._fixture(journal, run_id, context, boundary, create=before is None)
                flow = fixture.flow
                fixture._checkpoint = lambda command, data: self._checkpoint(fixture, command, data)
                try:
                    if name == 'CreateRun':
                        fixture.act('accept_inventory', observations=flow.inventory_observations())
                        fixture.act('workspace_clear', confirmed=True)
                        fixture.act('claim')
                    elif name == 'ResumeRun':
                        if not args['resume']:raise TaskError('Explicit resume=true required')
                        last = before['clock']['last_sample']
                        fixture.clock = FixtureClock(clock_id=fixture.time_basis + '.' + self.boot_id,
                            process_id=self.boot_id)
                        # This is a new declared test domain, not a measured gap.
                        fixture.clock.record['utc'] = last['utc']
                        flow = NetworkInputSonicationWorkflow.open(journal, run_id, resume=True,
                            clock=fixture.clock, control=self._binding(), command_context=context,
                            transition_guard=boundary)
                        fixture.flow = flow; self._sessions[run_id] = flow.session
                    elif name == 'RunUntilDecision':self._run(fixture)
                    elif name in {'ReconcileRun', 'FinishCancel'}:
                        self._reconcile(fixture, args['observation_json'], finish=name == 'FinishCancel')
                    elif name == 'CancelRun':fixture.act('cancel', reason=args['reason'])
                    response = {'run_id': run_id, 'request_id': request_id, 'command': name,
                        'execution_uuid': execution_uuid, 'outcome': 'completed',
                        'root_status': flow.state['status'], 'error': None}
                    flow.finish_command(response)
                    return response
                except (TaskError, PermissionError, ValueError, TypeError) as error:
                    own = flow.state.get('network', {}).get('commands', {}).get(request_id)
                    if own is None:raise
                    interrupted = isinstance(error, (ExecutionInterrupted, PermissionError))
                    pending = flow.state['pending_operation'] is not None
                    code = ('ReconciliationRequired' if pending else 'CommandCanceled') if interrupted else 'WorkflowRejected'
                    if interrupted and flow.state['status'] not in {'completed', 'cancelled'}:
                        def hold(current):
                            current['recovery_required'] = current['recovery_required'] or 'execution_interrupted'
                            current['workspace_clear'] = False
                        flow.control_event('execution_interrupted', hold, {'error': code}, trusted=True)
                    response = {'run_id': run_id, 'request_id': request_id, 'command': name,
                        'execution_uuid': execution_uuid, 'outcome': 'interrupted' if interrupted else 'failed',
                        'root_status': flow.state['status'], 'error': code, 'message': str(error)}
                    flow.finish_command(response, outcome=response['outcome'], error=code)
                    return response
        finally:
            self._cancellations.pop(execution_uuid, None)

    def _pause(self, point, flow):
        if self.pause_after == point:
            while not self._closed.wait(0.05):flow.transition_guard()
            raise ExecutionInterrupted('Server stopped at private test boundary')

    def _checkpoint(self, fixture, command, data):
        point = None
        if command == 'complete_stage' and data['stage_run_id'] == fixture.prefix + '.Stage.S01':point = 'opening_complete'
        if command == 'begin_material_action':
            point = {fixture.prefix + '.InputPreparation': 'input_preparation_intent',
                     fixture.prefix + '.SizeWithdrawal': 'qc_withdrawal_intent'}.get(data['intent_id'])
        if command == 'record_phase_time':point = 'phase_time'
        if command == 'confirm_material_action' and data['intent_id'] == fixture.prefix + '.SizeWithdrawal':point = 'qc_confirmed'
        if point:self._pause(point, fixture.flow)

    def _run(self, fixture):
        flow = fixture.flow
        state = flow.state
        stage = state['sop']['stages'].get(fixture.stage_run_id)
        if stage and stage['status'] == 'completed':return
        if state['recovery_required']:
            raise TaskError('Explicit reconciliation is required before continuing')
        if state['actor_id'] is None:
            if state['status'] != 'ready' or not state['workspace_clear']:
                raise TaskError('Explicit initial inventory reconciliation required before claiming the fixture')
            fixture.act('claim')
        if stage is None:fixture.prepare_input(resume=True)
        state = flow.state
        if fixture.intent_id not in state['bookings']:
            fixture.begin(); self._pause('sonication_intent', flow)
            fixture.confirm(); self._pause('sonication_confirmed', flow)
        elif state['bookings'][fixture.intent_id]['outcome'] != 'performed':
            raise TaskError('Open or unknown sonication intent must not be replayed')
        # Substeps are resumable by their persisted original IDs, not by retrying
        # an uncertain effect. The parent command's exact retry never enters here.
        stage = flow.state['sop']['stages'][fixture.stage_run_id]
        fixture.phase_evidence(resume=True)
        meta = flow.state['manual']['actions'][fixture.intent_id]['sonication']
        if not meta['size_records']:
            if fixture.prefix + '.SizeWithdrawal' in flow.state['bookings']:
                if flow.state['bookings'][fixture.prefix + '.SizeWithdrawal']['outcome'] != 'performed':
                    raise TaskError('Existing QC withdrawal needs explicit resolution; no second aliquot')
                fixture.size_result()
            else:fixture.size_evidence()
        fixture.complete()

    @staticmethod
    def _document(raw):
        if not isinstance(raw, str) or len(raw.encode()) > 262144:
            raise TaskError('Bounded explicit fixture reconciliation JSON required')
        data = json.loads(raw)
        expected = {'format', 'evidence_ref', 'reason', 'observations', 'workspace_clear',
                    'clock_gap', 'sonication', 'dispositions'}
        if (not isinstance(data, dict) or set(data) not in (expected, expected | {'material'}) or data['format'] != RECONCILIATION
                or data['evidence_ref'] != 'decision_evidence' or type(data['workspace_clear']) is not bool
                or not isinstance(data['observations'], list) or not isinstance(data['dispositions'], list)):
            raise TaskError('Exact explicit fixture reconciliation document required')
        text(data['reason'], 'fixture reconciliation reason')
        gap = data['clock_gap']
        if gap is not None:
            if not isinstance(gap, dict) or set(gap) != {'minimum_s', 'maximum_s'}:
                raise TaskError('Explicit clock gap interval required')
            if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in gap.values()) or gap['maximum_s'] < gap['minimum_s']:
                raise TaskError('Invalid explicit clock gap interval')
        return data

    def _reconcile(self, fixture, raw, *, finish=False):
        data = self._document(raw);flow = fixture.flow;state = flow.state
        if finish and state['status'] != 'cancelling':raise TaskError('CancelRun is required first')
        if not finish and data['dispositions']:
            raise TaskError('Only FinishCancel accepts final material dispositions')
        if not data['workspace_clear']:raise TaskError('Explicit complete workspace observation required')
        pending = state['pending_operation'];resolution = data['sonication'];material = data.get('material')
        if resolution is not None and material is not None:
            raise TaskError('One explicit pending effect resolution required')
        if pending:
            if pending['intent_id'] == fixture.intent_id:
                if not isinstance(resolution, dict):raise TaskError('Explicit sonication outcome required')
                outcome = resolution.get('outcome')
                fields = {'outcome', 'actual_output_quantity', 'observed_vessel_id'} if outcome == 'performed' else {'outcome'}
                if set(resolution) != fields or outcome not in {'performed', 'not_performed', 'unknown'}:
                    raise TaskError('Exact explicit sonication resolution required')
                if outcome == 'performed' and (resolution['actual_output_quantity'] != {'value': fixture.fixture['input_lysate_ul'], 'unit': 'uL'} or resolution['observed_vessel_id'] != fixture.vessel_id):
                    raise TaskError('Resolution must identify the pinned fixture quantity and vessel')
            else:
                if resolution is not None or not isinstance(material, dict):
                    raise TaskError('Explicit known preparation or QC outcome required')
                _validate_material_resolution(fixture, state, material)
        elif resolution is not None or material is not None:
            raise TaskError('No pending effect to resolve')
        selected = resolution if resolution is not None else material
        if finish and selected and selected['outcome'] == 'unknown':
            raise TaskError('Unknown effect cannot finish cancellation or release resources')
        # Check explicit *post-resolution* inventory on an uncommitted ledger
        # proposal. The real observation and effect still use canonical acts.
        proposal = copy.deepcopy(state)
        if resolution and resolution['outcome'] == 'performed':
            _preview_performed(proposal, fixture.actor, fixture.intent_id, resolution['actual_output_quantity'])
        if material and material['outcome'] == 'performed':
            _preview_material(proposal, fixture.actor, material)
        proposal['observation_context'] = fixture.envelope()
        if selected and selected['outcome'] == 'not_performed':
            ledger.not_performed(proposal, fixture.actor, pending['intent_id'], data['reason'])
        if finish:
            origin = InputSonicationWorkflow._origin(state, fixture.vessel_id)
            expected = {identity for identity, material in proposal['inventory']['materials'].items()
                        if material['disposition'] != 'consumed' and material['disposition_confirmation'] is None}
            if {item.get('material_id') for item in data['dispositions'] if isinstance(item, dict)} != expected or len(data['dispositions']) != len(expected):
                raise TaskError('Complete explicit material dispositions required')
            for item in data['dispositions']:
                if set(item) != {'material_id', 'disposition', 'reason'} or item['disposition'] not in {'retained', 'discarded'}:
                    raise TaskError('Explicit final fixture disposition required')
                text(item['reason'], 'disposition reason')
            for item in data['dispositions']:
                ledger.set_disposition(proposal, fixture.actor, **item)
        flow._confirm_inventory(proposal, fixture.actor, data['observations'])
        if finish and proposal['inventory']['vessels'][fixture.vessel_id]['location'] != origin:
            raise TaskError('FinishCancel requires explicit return to the original rack place')
        if state['clock']['gap_required'] and data['clock_gap'] is None and not finish:
            raise TaskError('Explicit clock gap reconciliation required')
        if state['clock']['gap_required'] and data['clock_gap'] is not None:
            fixture.act('resolve_clock_gap', **data['clock_gap'], reason=data['reason'], evidence_ref=data['evidence_ref'])
        if pending:
            original = encoded({'fixture_only': True, 'fixture_sha256': digest(fixture.evidence_files['decision_evidence'].read_bytes()),
                                'intent_id': pending['intent_id'], 'declared_resolution': selected}).encode()
            if resolution is not None:
                fixture.act('resolve_sonication', intent_id=fixture.intent_id, reason=data['reason'],
                            artifact=original if resolution['outcome'] == 'performed' else None, **resolution)
            else:
                fixture.act('resolve_action', intent_id=material['intent_id'], outcome=material['outcome'],
                    actual_inputs=material.get('actual_inputs', []), actual_outputs=material.get('actual_outputs', []),
                    mixed=None, reason=data['reason'], artifact=original if material['outcome'] == 'performed' else None)
        if selected and selected['outcome'] == 'unknown':return
        for item in data['dispositions']:fixture.act('set_disposition', **item)
        if flow.state['status'] == 'created':
            fixture.act('accept_inventory', observations=data['observations'])
        else:fixture.act('confirm_inventory', observations=data['observations'])
        fixture.act('reconcile', observations=data['observations'], workspace_clear=True, reason=data['reason'])
        if finish:fixture.act('finish_cancel', workspace_clear=True)


def _preview_performed(state, actor_id, intent_id, quantity):
    state['observation_context'] = {'observation_id': 'Client.Fixture.Proposal', 'source_kind': 'test_fixture',
        'observed_at': None, 'source_ref': 'fixture://explicit-client-proposal', 'artifact_sha256': None}
    meta = state['manual']['actions'][intent_id]['sonication']
    ledger.confirm_effect(state, actor_id, intent_id,
        [{'material_id': meta['material_before_id'], 'quantity': meta['quantity_before']}],
        [{'material_id': meta['material_after_id'], 'quantity': quantity}], 'Uncommitted fixture proposal')
    state['manual']['reactions'][meta['reaction_id']]['current_material_id'] = meta['material_after_id']


def _material_actuals(state, intent_id):
    request = state['bookings'][intent_id]['request']
    inputs = [{'material_id': item['material_id'], 'quantity': copy.deepcopy(item['quantity'])}
              for item in request['inputs']]
    outputs = [{'material_id': item['material_id'],
                'quantity': {'value': fixture_values()['input_lysate_ul'], 'unit': 'uL'}}
               for item in request['outputs']]
    return inputs, outputs


def _validate_material_resolution(fixture, state, material):
    intent = state['pending_operation']['intent_id']
    allowed = {fixture.prefix + '.InputPreparation', fixture.prefix + '.SizeWithdrawal'}
    outcome = material.get('outcome')
    fields = {'intent_id', 'outcome', 'actual_inputs', 'actual_outputs'} if outcome == 'performed' else {'intent_id', 'outcome'}
    if intent not in allowed or material.get('intent_id') != intent or set(material) != fields or outcome not in {'performed', 'not_performed', 'unknown'}:
        raise TaskError('Exact known fixture material resolution required')
    if outcome == 'performed':
        inputs, outputs = _material_actuals(state, intent)
        if material['actual_inputs'] != inputs or material['actual_outputs'] != outputs:
            raise TaskError('Resolution must declare the pinned fixture inputs and outputs')


def _preview_material(state, actor_id, material):
    state['observation_context'] = {'observation_id': 'Client.Fixture.MaterialProposal', 'source_kind': 'test_fixture',
        'observed_at': None, 'source_ref': 'fixture://explicit-client-proposal', 'artifact_sha256': None}
    ledger.confirm_effect(state, actor_id, material['intent_id'], material['actual_inputs'],
                          material['actual_outputs'], 'Uncommitted fixture material proposal')
    action = state['manual']['actions'][material['intent_id']]
    if action.get('retained_material_id') is not None:
        state['manual']['reactions'][action['reaction_id']]['current_material_id'] = action['retained_material_id']


def reconciliation_document(report, *, outcome=None, gap_s=25, return_to_origin=False, finish=False):
    """Explicit *client-side* software-fixture proposal; never called by server.

    The caller must inspect/select these synthetic observations before sending.
    This is not an inventory scan or a real operator confirmation.
    """
    if not report.get('trace') or 'state' not in report['trace'][-1]:
        return _wire_reconciliation_document(report, outcome, gap_s, return_to_origin, finish)
    state = copy.deepcopy(report['trace'][-1]['state'])
    resolution, material = _client_resolution(state, outcome)
    if outcome == 'performed':
        if material is not None:_preview_material(state, fixture_values()['actor_id'], material)
        else:_preview_performed(state, fixture_values()['actor_id'], state['pending_operation']['intent_id'],
                                resolution['actual_output_quantity'])
    from material_workflow import MaterialWorkflow
    inventory = MaterialWorkflow.inventory_observations.__get__(type('View', (), {'state': state})())()
    input_id = state['definition']['runtime_profile']['bindings']['input_reaction_id']
    vessel_id = state['manual']['reactions'][input_id]['vessel_id']
    if return_to_origin:
        origin = next(item['location'] for item in state['definition']['initial_vessels'] if item['id'] == vessel_id)
        for item in inventory:
            if item['vessel_id'] == vessel_id:item['location'] = copy.deepcopy(origin)
    dispositions = []
    if finish:
        dispositions = [{'material_id': identity, 'disposition': 'retained', 'reason': 'Explicit client fixture retention'}
                        for identity, item in state['inventory']['materials'].items()
                        if item['disposition'] != 'consumed' and item['disposition_confirmation'] is None]
    result = {'format': RECONCILIATION, 'evidence_ref': 'decision_evidence',
            'reason': 'Explicit client-selected synthetic fixture reconciliation, no scan or hardware',
            'observations': inventory, 'workspace_clear': True,
            'clock_gap': {'minimum_s': gap_s, 'maximum_s': gap_s} if state['clock']['gap_required'] else None,
            'sonication': resolution, 'dispositions': dispositions}
    if material is not None:result['material'] = material
    return result


def _client_resolution(view, outcome):
    if outcome is None:return None, None
    pending = view['pending_operation']
    if pending is None:raise TaskError('No pending effect for the explicit client proposal')
    intent_id = pending['intent_id']
    action = view['manual']['actions'][intent_id]
    if 'sonication' in action:
        resolution = {'outcome': outcome}
        if outcome == 'performed':
            resolution.update(actual_output_quantity={'value': fixture_values()['input_lysate_ul'], 'unit': 'uL'},
                              observed_vessel_id=action['sonication']['vessel_id'])
        return resolution, None
    resolution = {'intent_id': intent_id, 'outcome': outcome}
    if outcome == 'performed':
        inputs, outputs = _material_actuals(view, intent_id)
        resolution.update(actual_inputs=inputs, actual_outputs=outputs)
    return None, resolution


def _wire_reconciliation_document(report, outcome, gap_s, return_to_origin, finish):
    """Client proposal from the bounded wire view; no hidden Root access."""
    if report.get('wire_projection', {}).get('format') != 'solidcraftbot.s09-sila2-wire-report/1':
        raise TaskError('Explicit full Root report or versioned wire report required')
    inventory = report['inventory']
    observations = [{'vessel_id': identity,
        'material_ids': [key for key, item in inventory['materials'].items() if item['vessel_id'] == identity],
        'location': copy.deepcopy(vessel['location'])} for identity, vessel in inventory['vessels'].items()]
    context = report['transport_receipts']['fixture_context']
    resolution, material = _client_resolution(report, outcome)
    removed, added = set(), set()
    if outcome == 'performed':
        if resolution is not None:
            intent = report['manual']['actions'][report['pending_operation']['intent_id']]['sonication']
            removed.add(intent['material_before_id']);added.add(intent['material_after_id'])
        elif material is not None and material['actual_outputs']:
            request = report['bookings'][material['intent_id']]['request']
            removed.update(item['material_id'] for item in request['inputs'] if item['consume_all'])
            added.update(item['material_id'] for item in material['actual_outputs'])
        for item in observations:
            if item['vessel_id'] == context['vessel_id']:
                item['material_ids'] = [identity for identity in item['material_ids'] if identity not in removed]
                item['material_ids'].extend(sorted(added))
    if return_to_origin:
        for item in observations:
            if item['vessel_id'] == context['vessel_id']:
                item['location'] = copy.deepcopy(context['original_rack_location'])
    dispositions = []
    if finish:
        identities = {identity for identity, item in inventory['materials'].items()
                      if item['disposition'] != 'consumed' and item['disposition_confirmation'] is None}
        identities.difference_update(removed);identities.update(added)
        dispositions = [{'material_id': identity, 'disposition': 'retained',
                         'reason': 'Explicit client fixture retention'} for identity in sorted(identities)]
    result = {'format': RECONCILIATION, 'evidence_ref': 'decision_evidence',
        'reason': 'Explicit client-selected synthetic fixture reconciliation, no scan or hardware',
        'observations': observations, 'workspace_clear': True,
        'clock_gap': {'minimum_s': gap_s, 'maximum_s': gap_s} if report['clock']['gap_required'] else None,
        'sonication': resolution, 'dispositions': dispositions}
    if material is not None:result['material'] = material
    return result
