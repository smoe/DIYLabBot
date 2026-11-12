"""One versioned synthetic material lifecycle for extraction and CUT&RUN.

This executes explicit material observations, not either biochemical protocol.
Journal, sessions, deadlines and recovery dispatch use the existing common
manual workflow; there is no domain-specific database or second live balance.
"""

import copy
import re
import uuid

from manual_tasks import TaskError, digest, encoded
from manual_workflow import ManualWorkflow, ObservationError
import material_ledger as ledger
from material_workflow_sources import load


class MaterialWorkflow(ManualWorkflow):
    STATE_FORMAT = 'solidcraftbot.material-workflow-state/1'
    REPORT_FORMAT = 'solidcraftbot.material-workflow-report/1'
    DEADLINE_FIELD = 'deadline_s'
    EVENT_CLOCK = True
    STEPS = ('accept_inventory', 'confirm_inventory', 'workspace_clear', 'claim',
             'begin_effect', 'confirm_effect', 'mark_unknown', 'not_performed',
             'set_disposition', 'record_measurement', 'resolve_quantity', 'release', 'advance_time')
    RECOVERY_COMMANDS = {'reconcile', 'cancel', 'check_deadline'}
    CANCELLING_COMMANDS = {'reconcile', 'set_disposition', 'confirm_inventory',
                           'resolve_quantity', 'finish_cancel', 'check_deadline'}

    @classmethod
    def create(cls, journal, domain, source=None, *, materials, vessels, run_id=None, task_deadline_s=3600):
        definition = load(domain, source, materials=materials, vessels=vessels, task_deadline_s=task_deadline_s)
        identity = run_id or 'SYN.MATERIAL.' + uuid.uuid4().hex[:12]
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', identity):
            raise TaskError('Run id requires 1-64 ASCII letters, digits, dots, underscores or hyphens')
        session = uuid.uuid4().hex
        inventory = ledger.initial_inventory(definition['initial_materials'], definition['initial_vessels'])
        state = {'format': cls.STATE_FORMAT, 'run_id': identity, 'attempt_id': identity + '.A01',
                 'definition': definition, 'status': 'created', 'session': session,
                 'actor_id': None, 'resources': [], 'rack_ready': False, 'workspace_clear': False,
                 'recovery_required': None, 'deadline_s': None, 'logical_time_s': 0.0,
                 'inventory': inventory, 'inventory_confirmation': None, 'bookings': {},
                 'pending_operation': None, 'imports': {}, 'cancel_reason': None}
        state['resources'] = cls._resources(state)
        journal.create(identity, state, immutable_definition=True,
                       material_allocations=definition['material_allocations'])
        return cls(journal, identity, session)

    @staticmethod
    def _resources(state):
        result = {'vessel:' + identity for identity in state['inventory']['vessels']}
        result.update('material:' + identity for identity in state['inventory']['materials'])
        pending = state.get('pending_operation')
        if pending:
            booking = state['bookings'][pending['intent_id']]
            result.update('material:' + item['material_id'] for item in booking['request']['outputs'])
        return sorted(result)

    def _pending(self, state):
        return state['pending_operation']

    @staticmethod
    def _inventory_digest(state):
        return digest(encoded(state['inventory']).encode())

    def _inventory(self, state, observations, actor_id):
        vessels = state['inventory']['vessels']
        if not isinstance(observations, list) or len(observations) != len(vessels):
            raise ObservationError('Complete per-vessel material inventory required')
        found, occupied, held = {}, set(), 0
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) != {'vessel_id', 'material_ids', 'location'}:
                raise ObservationError('Explicit vessel, material identities and location required')
            identity = observation['vessel_id']
            if not isinstance(identity, str) or identity not in vessels or identity in found:
                raise ObservationError('Unknown or duplicate observed vessel')
            materials = observation['material_ids']
            expected = {key for key, item in state['inventory']['materials'].items()
                        if item['vessel_id'] == identity}
            if (not isinstance(materials, list) or any(not isinstance(item, str) for item in materials)
                    or len(materials) != len(set(materials)) or set(materials) != expected):
                raise ObservationError('Observed vessel/material identity mismatch')
            try:
                location = ledger.location(observation['location'])
            except TaskError as error:
                raise ObservationError('Invalid observed physical location: ' + str(error)) from error
            kind = location['kind']
            if kind == 'operator':
                if location['actor_id'] != actor_id:
                    raise ObservationError('Observed vessel holder differs from task actor')
                held += 1
                if held > 1:
                    raise ObservationError('Multiple hand-held vessels are not supported')
            if kind == 'discarded' and expected:
                raise ObservationError('A discarded vessel cannot contain retained material')
            key = encoded(location)
            if kind != 'discarded' and key in occupied:
                raise ObservationError('Duplicate occupied vessel location')
            if kind != 'discarded':
                occupied.add(key)
            found[identity] = copy.deepcopy(location)
        return found

    def inventory_observations(self):
        state = self.state
        return [{'vessel_id': identity, 'material_ids': [key for key, material in state['inventory']['materials'].items()
                                                       if material['vessel_id'] == identity],
                 'location': copy.deepcopy(vessel['location'])}
                for identity, vessel in state['inventory']['vessels'].items()]

    def _confirm_inventory(self, state, actor_id, observations):
        if state['status'] not in {'created', 'ready', 'working', 'cancelling'}:
            raise TaskError('Open material inventory required before confirmation')
        found = self._inventory(state, observations, actor_id)
        for identity, location in found.items():
            state['inventory']['vessels'][identity]['location'] = location
        state['inventory_confirmation'] = {'actor_id': actor_id, 'evidence': 'synthetic_input',
                                           'inventory_sha256': self._inventory_digest(state)}

    def _accept_inventory(self, state, actor_id, observations):
        if state['status'] != 'created':
            raise TaskError('Initial material inventory was already accepted')
        found = self._inventory(state, observations, actor_id)
        if any(location != state['inventory']['vessels'][identity]['location'] for identity, location in found.items()):
            raise ObservationError('Initial material fixture location mismatch')
        state['status'], state['rack_ready'] = 'ready', True
        self._confirm_inventory(state, actor_id, observations)

    @staticmethod
    def _assign_responsibility(state, actor_id):
        for vessel in state['inventory']['vessels'].values():
            vessel['responsibility'] = {'kind': 'actor', 'actor_id': actor_id}
        state['inventory_confirmation'] = None

    def _claim(self, state, actor_id):
        super()._claim(state, actor_id)
        self._assign_responsibility(state, actor_id)

    def _after_material_change(self, state, changed):
        if changed is False:
            return False
        state['inventory_confirmation'] = None
        state['resources'] = self._resources(state)
        return changed

    def _begin_effect(self, state, actor_id, intent_id, kind, inputs, outputs, purpose):
        self._claimed(state)
        planned = {item['material_id']: item for item in state['definition']['products']}
        parents = ({item['material_id'] for item in inputs
                    if isinstance(item, dict) and isinstance(item.get('material_id'), str)}
                   if isinstance(inputs, list) else set())
        if isinstance(outputs, list):
            for output in outputs:
                if (isinstance(output, dict) and isinstance(output.get('material_id'), str)
                        and output['material_id'] in planned):
                    binding = planned[output['material_id']]
                    if output.get('vessel_id') != binding['vessel_id'] or output.get('kind') != 'product':
                        raise TaskError('Declared preparation product binding mismatch')
                    if binding['parent_material_id'] not in parents:
                        raise TaskError('Declared preparation product parent binding mismatch')
        return self._after_material_change(state, ledger.begin_effect(
            state, actor_id, intent_id, kind, inputs, outputs, purpose))

    def _confirm_effect(self, state, actor_id, intent_id, actual_inputs, actual_outputs, reason):
        self._claimed(state)
        return self._after_material_change(state, ledger.confirm_effect(
            state, actor_id, intent_id, actual_inputs, actual_outputs, reason))

    def _mark_unknown(self, state, actor_id, intent_id, reason):
        self._claimed(state)
        return self._after_material_change(state, ledger.mark_unknown(state, actor_id, intent_id, reason))

    def _not_performed(self, state, actor_id, intent_id, reason):
        self._claimed(state)
        return self._after_material_change(state, ledger.not_performed(state, actor_id, intent_id, reason))

    def _set_disposition(self, state, actor_id, material_id, disposition, reason):
        self._claimed(state)
        return self._after_material_change(state, ledger.set_disposition(
            state, actor_id, material_id, disposition, reason))

    def _record_measurement(self, state, actor_id, material_id, measurement_id, kind, quantity, reason):
        self._claimed(state)
        return self._after_material_change(state, ledger.record_measurement(
            state, actor_id, material_id, measurement_id, kind, quantity, reason))

    def _resolve_quantity(self, state, actor_id, intent_id, material_id, quantity, reason):
        self._claimed(state)
        return self._after_material_change(state, ledger.resolve_quantity(
            state, actor_id, intent_id, material_id, quantity, reason))

    def _reconcile(self, state, actor_id, observations, workspace_clear, intent_id=None,
                   outcome=None, actual_inputs=None, actual_outputs=None, reason=None):
        if not state['recovery_required']:
            raise TaskError('No material reconciliation is pending')
        if type(workspace_clear) is not bool:
            raise TaskError('Explicit workspace observation required')
        pending = self._pending(state)
        if pending:
            if intent_id != pending['intent_id']:
                raise ObservationError('Explicit pending material intent identity required')
            if outcome == 'performed':
                ledger.confirm_effect(state, actor_id, intent_id, actual_inputs, actual_outputs, reason)
            elif outcome == 'not_performed':
                ledger.not_performed(state, actor_id, intent_id, reason)
            elif outcome == 'unknown':
                ledger.mark_unknown(state, actor_id, intent_id, reason)
                state['inventory_confirmation'] = None
                state['workspace_clear'] = False
                return
            else:
                raise TaskError('Explicit performed, not_performed or unknown outcome required')
        elif outcome is not None or intent_id is not None or actual_inputs is not None or actual_outputs is not None:
            raise TaskError('No pending material operation can be reconciled')
        self._confirm_inventory(state, actor_id, observations)
        state['recovery_required'] = None
        state['workspace_clear'] = workspace_clear
        state['resources'] = self._resources(state)
        if state['actor_id']:
            state[self.DEADLINE_FIELD] = self._now(state) + state['definition']['profile']['parameters']['task_deadline_s']

    def _cancel(self, state, actor_id, reason):
        if state['actor_id'] is None:
            state['actor_id'] = actor_id
            self._assign_responsibility(state, actor_id)
        return super()._cancel(state, actor_id, reason)

    def _audit_artifacts(self, trace):
        for event in trace:
            checksum = event['payload'].get('artifact_sha256')
            if checksum is not None:
                self.journal.artifact(checksum)

    def _restored(self, state):
        ledger.audit(state)
        if self._pending(state):
            raise TaskError('Resolve every pending material operation before handover')
        if any(item['disposition'] is None or not item['disposition_confirmation']
               for item in state['inventory']['materials'].values()):
            raise TaskError('Explicit disposition of every material required')
        confirmation = state['inventory_confirmation']
        if not confirmation or confirmation['inventory_sha256'] != self._inventory_digest(state):
            raise TaskError('Fresh complete material inventory confirmation required')
        self._audit_artifacts(self.journal.history(self.run_id))
        self.journal.audit_material_allocations()

    def _release(self, state, actor_id, workspace_clear):
        self._claimed(state)
        self._require(workspace_clear, 'Final material work-area handback confirmation missing')
        self._restored(state)
        self._finish_lifecycle(state, 'completed')

    def act(self, command, actor_id, artifact=None, **data):
        if command in {'take', 'place', 'discard_import', 'dispose_vessel', 'import_results', 'review_results', 'rack_ready'}:
            raise TaskError('Legacy sample/measurement command is not supported by the material lifecycle')
        return super().act(command, actor_id, artifact=artifact, **data)

    def _report(self, state, trace):
        ledger.audit(state)
        self._audit_artifacts(trace)
        allocations = self.journal.audit_material_allocations()
        measurement_validity = {}
        balances = {identity: ledger.remaining(state, identity) for identity in state['inventory']['materials']}
        pending = state['pending_operation']
        pending_inputs = (set() if pending is None else
                          {item['material_id'] for item in state['bookings'][pending['intent_id']]['request']['inputs']})
        for identity, material in state['inventory']['materials'].items():
            vessel_id = material['vessel_id']
            vessel = state['inventory']['vessels'].get(vessel_id)
            quantity_known = balances[identity]['knowledge'] not in {
                'unresolved_operation', 'confirmed_quantity_unknown'}
            measurement_validity[identity] = {}
            for measurement_id, record in material['measurements'].items():
                valid = bool(vessel is not None and record['quantity']['value'] is not None
                             and record['vessel_id'] == vessel_id
                             and record['content_revision'] == vessel['content_revision']
                             and identity not in pending_inputs and quantity_known)
                if valid and record['kind'] == 'total_vessel_mass':
                    valid = bool(vessel['mass_confirmation_valid'])
                measurement_validity[identity][measurement_id] = valid
        return {'format': self.REPORT_FORMAT, 'run_id': self.run_id, 'mode': 'synthetic_only',
                'domain': state['definition']['domain'], 'status': state['status'],
                'passed': state['status'] == 'completed', 'inventory': copy.deepcopy(state['inventory']),
                'bookings': copy.deepcopy(state['bookings']),
                'remaining': balances,
                'measurement_validity': measurement_validity,
                'pending_operation': copy.deepcopy(state['pending_operation']),
                'resources': copy.deepcopy(state['resources']), 'recovery_required': state['recovery_required'],
                'material_allocations': {key: value for key, value in allocations.items() if value['run_id'] == self.run_id},
                'source_files_sha256': copy.deepcopy(state['definition']['source_files_sha256']),
                'effective_profile_sha256': state['definition']['effective_profile_sha256'],
                'preparation_execution_ready': state['definition']['preparation_plan']['execution_ready'],
                'network_executed': False, 'hardware_executed': False,
                'biochemical_protocol_executed': False, 'safety_function_qualified': False,
                'limitations': ['Explicit synthetic material observations only; no extraction or CUT&RUN chemistry runtime.',
                                'No reagent recipe or yield is inferred from preparation phase volumes.',
                                'No cross-run stock quantity continuation, hardware or biological qualification.'],
                'trace': trace}
