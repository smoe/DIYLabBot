"""One durable, entirely synthetic CF01 -> NanoDrop -> Qubit workflow.

No transport or hardware adapter is imported. CF01 callbacks persist intent and
observations; interrupted CF01 attempts require cancellation reconciliation.
"""
import copy
import inspect
import json
import re
import uuid
from pathlib import Path

from cf01_rack_batch import Runner, BatchError, ProcessHold
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, ObservationError, positive, text
from lab_workflow_sources import load, SOURCE, STAGES, build_cf01_profile, validate_mass_confirmation
from lab_workflow_ledger import (initial_inventory, manifest_samples, original_location,
                                 remaining, StageState, begin_withdrawal)
from lab_workflow_stages import ADAPTERS, StageHandle, initial_stage

FORMAT = 'solidcraftbot.synthetic-lab-state/1'
RUNTIME = ['scripts/lab_workflow.py', 'scripts/lab_workflow_ledger.py',
           'scripts/lab_workflow_stages.py', 'scripts/run_lab_workflow.py']
TERMINAL = {'completed', 'cancelled'}


class Workflow:
    def __init__(self, journal, run_id, session=None):
        self.journal, self.run_id, self.session = journal, run_id, session
        self._format(self.state)

    @staticmethod
    def _format(state):
        if state.get('format') != FORMAT:
            raise TaskError('Wrong workflow format; integrated workflow required')

    @property
    def state(self):
        state, _ = self.journal.get_current(self.run_id)
        self._format(state)
        return state

    @classmethod
    def create(cls, journal, source=SOURCE, run_id=None):
        definition = load(source, runtime_sources=RUNTIME)
        run_id = run_id or 'SYN.LAB.' + uuid.uuid4().hex[:12]
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise TaskError('Run id requires 1-64 ASCII letters, digits, dots, underscores or hyphens')
        session = uuid.uuid4().hex
        state = {'format': FORMAT, 'run_id': run_id, 'definition': definition,
                 'status': 'created', 'active_stage': 'cf01', 'session': session,
                 'clock_mode': 'synthetic_events/1', 'logical_time_s': 0.0,
                 'deadline_s': definition['profile']['task_deadline_s'],
                 'resources': [], 'recovery_required': None, 'bookings': {},
                 'mass_confirmations': {}, 'inventory': initial_inventory(definition),
                 'stages': {'cf01': {'status': 'waiting', 'actor_id': None,
                     'attempt_id': run_id + '.cf01.A01', 'deadline_s': None,
                     'recovery_required': None, 'view': None, 'report_artifact_sha256': None,
                     'pending_command': None}},
                 'cancel_reason': None}
        for stage_id in ['nanodrop', 'qubit']:
            state['stages'][stage_id] = initial_stage(run_id, definition['stages'][stage_id], stage_id)
        journal.create(run_id, state)
        return cls(journal, run_id, session)

    @classmethod
    def open(cls, journal, run_id, resume=False):
        state, revision = journal.get_current(run_id, verify=True)
        cls._format(state)
        if state['status'] in TERMINAL:
            return cls(journal, run_id)
        if state['clock_mode'] != 'synthetic_events/1':
            raise TaskError('Integrated process clock mode changed')
        for file, checksum in state['definition']['source_files_sha256'].items():
            path = (ROOT / file).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file() or digest(path.read_bytes()) != checksum:
                raise TaskError('Pinned source changed; deliberate migration required: ' + file)
        if state['session'] and not resume:
            raise TaskError('Previous session is open; explicit resume required')
        session = uuid.uuid4().hex
        state['session'] = session
        if state['resources']:
            stage = state['stages'][state['active_stage']]
            reason = ('cf01_context_lost' if state['active_stage'] == 'cf01' and stage['status'] != 'ready'
                      else 'session_restarted')
            state['recovery_required'] = state['recovery_required'] or reason
            stage['recovery_required'] = stage['recovery_required'] or reason
            if state['status'] != 'cancelling': state['status'] = 'held'
        journal.append(run_id, revision, 'session_opened', {'explicit_resume': resume}, state)
        return cls(journal, run_id, session)

    def close(self):
        state, revision = self.journal.get_current(self.run_id)
        if self.session and state['session'] == self.session:
            state['session'] = None
            self.journal.append(self.run_id, revision, 'session_closed', {}, state)
        self.session = None

    def _transition(self, kind, actor_id, update, payload=None, artifact=None):
        text(actor_id, 'synthetic actor id')
        before, revision = self.journal.get_current(self.run_id)
        self._format(before)
        if before['status'] in TERMINAL:
            raise TaskError('Workflow is terminal')
        if self.session is None or before['session'] != self.session:
            raise TaskError('Stale workflow session; reopen and reconcile')
        state = copy.deepcopy(before)
        try:
            result = update(state)
        except ObservationError as error:
            if before['status'] != 'cancelling': before['status'] = 'held'
            before['recovery_required'] = before['recovery_required'] or 'observation_mismatch'
            before['stages'][before['active_stage']]['recovery_required'] = 'observation_mismatch'
            self.journal.append(self.run_id, revision, 'observation_rejected',
                                {**(payload or {}),'command': kind, 'actor_id': actor_id, 'error': str(error)}, before)
            raise
        if result is False:
            return before
        self.journal.append(self.run_id, revision, kind,
                            {'actor_id': actor_id, 'evidence': 'synthetic_input', **(payload or {})},
                            state, artifact=artifact)
        return state

    @staticmethod
    def _resources(state):
        definition = state['definition']
        resources = ['workspace:' + definition['work_area']['id'], 'rack:' + definition['rack_instance']]
        resources += ['vessel:' + identity for identity in state['inventory']['vessels']]
        if state['active_stage'] == 'cf01':
            bindings=definition['profile']['bindings']
            resources += ['instrument:'+bindings['station_instance'], 'arm:'+bindings['arm_instance']]
        else:
            resources += ['instrument:' + definition['stages'][state['active_stage']]['profile']['instrument']['id']]
        return sorted(set(resources))

    def inventory_observations(self):
        return [{'vessel_id': identity, 'location': copy.deepcopy(vessel['location']),
                 **({'sample_id': vessel['sample_id']} if vessel['origin'] == 'original' else {})}
                for identity, vessel in self.state['inventory']['vessels'].items()]

    @staticmethod
    def _observations(state, observations):
        vessels = state['inventory']['vessels']
        if not isinstance(observations, list) or len(observations) != len(vessels):
            raise ObservationError('Complete per-vessel inventory required')
        found, occupied = {}, set()
        for observed in observations:
            if (not isinstance(observed, dict) or not isinstance(observed.get('vessel_id'),str)
                    or observed['vessel_id'] not in vessels):
                raise ObservationError('Unknown observed vessel')
            identity = observed['vessel_id']
            if identity in found:
                raise ObservationError('Duplicate observed vessel')
            vessel = vessels[identity]
            expected = {'vessel_id', 'location'} | ({'sample_id'} if vessel['origin'] == 'original' else set())
            if set(observed) != expected or ('sample_id' in observed and observed['sample_id'] != vessel['sample_id']):
                raise ObservationError('Sample/vessel observation mismatch')
            location = observed['location']
            if not isinstance(location, dict):
                raise ObservationError('Explicit physical location required')
            if vessel['origin'] == 'original':
                if location != original_location(state, vessel['sample_id']):
                    raise ObservationError('Confirmed return to every original place required')
            elif location != {'kind': 'discarded'} or not vessel.get('disposition_confirmation'):
                raise ObservationError('Explicit confirmed disposal of every derived vessel required')
            key = encoded(location)
            if location.get('kind') != 'discarded' and key in occupied:
                raise ObservationError('Duplicate occupied place')
            occupied.add(key)
            found[identity] = copy.deepcopy(location)
        return found

    def accept_rack(self, actor_id, observations):
        def update(state):
            if state['status'] != 'created': raise TaskError('Rack was already accepted')
            self._observations(state, observations)
            for vessel in state['inventory']['vessels'].values():
                vessel['return_confirmation'] = {'actor_id': actor_id, 'evidence': 'synthetic_input'}
                vessel['responsibility'] = {'kind': 'workflow', 'run_id': self.run_id}
            state['stages']['cf01']['status'] = 'ready'
            state['status'] = 'running'
            state['resources'] = self._resources(state)
        return self._transition('rack_accepted', actor_id, update, {'observations': observations})

    def reconcile_initial_cf01(self, actor_id, observations, rotor_empty, gripper_empty,
                               standstill_confirmed, parking_brake_held, lift_parked,
                               arm_clear, workspace_clear, evidence='synthetic_operator_confirmation'):
        def update(state):
            stage=state['stages']['cf01']
            if state['active_stage']!='cf01' or stage['status']!='ready' or stage['view'] is not None:
                raise TaskError('Only an unstarted CF01 stage can be reconciled for first execution')
            if state['logical_time_s']>=state['deadline_s']:
                raise TaskError('The original workflow deadline has expired')
            if evidence!='synthetic_operator_confirmation':
                raise TaskError('Explicit synthetic operator evidence required')
            if (not isinstance(rotor_empty,list) or any(type(slot) is not int for slot in rotor_empty)
                    or rotor_empty!=list(range(1,13)) or any(flag is not True for flag in
                    [gripper_empty,standstill_confirmed,parking_brake_held,lift_parked,arm_clear,workspace_clear])):
                raise ObservationError('Complete initial CF01 and work-area reconciliation required')
            self._observations(state,observations)
            stage['recovery_required']=None
            state.update(status='running',recovery_required=None)
            stage['initial_reconciliation']={'actor_id':actor_id,'evidence':evidence,
                'rotor_empty':rotor_empty,'gripper_empty':gripper_empty,'standstill_confirmed':standstill_confirmed,
                'parking_brake_held':parking_brake_held,'lift_parked':lift_parked,
                'arm_clear':arm_clear,'workspace_clear':workspace_clear,'time_s':state['logical_time_s']}
        return self._transition('cf01.initial_reconciled',actor_id,update,{'observations':observations})

    def confirm_mass(self, actor_id, vessel_id, mass_g, content_revision, confirmation_id=None):
        text(vessel_id,'original vessel identity')
        identity = confirmation_id or uuid.uuid4().hex
        def update(state):
            if state['status'] == 'created' or state['recovery_required']:
                raise TaskError('Reserved and reconciled inventory required')
            vessel = state['inventory']['vessels'].get(vessel_id)
            if not vessel or vessel['origin'] != 'original' or vessel['volume_uncertain']:
                raise TaskError('Known original vessel state required for mass confirmation')
            if content_revision != vessel['content_revision']:
                raise TaskError('Mass confirmation content revision is stale')
            record = validate_mass_confirmation({'confirmation_id': identity, 'vessel_id': vessel_id,
                'mass_g': mass_g, 'content_revision': content_revision, 'actor_id': actor_id,
                'time_s': state['logical_time_s'], 'evidence': 'synthetic_input'})
            if identity in state['mass_confirmations']:
                raise TaskError('Mass confirmation id already exists')
            state['mass_confirmations'][identity] = record
            vessel['mass_confirmation_id'], vessel['mass_confirmation_valid'] = identity, True
        return self._transition('mass_confirmed', actor_id, update, {'confirmation_id': identity, 'vessel_id': vessel_id})

    @staticmethod
    def cf01_profile(state):
        confirmations, revisions = {}, {}
        for sample in state['definition']['manifest']['samples']:
            identity = sample['vessel_id'];vessel = state['inventory']['vessels'][identity]
            if not vessel['mass_confirmation_valid'] or vessel['volume_uncertain']:
                raise TaskError('Fresh total vessel mass confirmation required: ' + identity)
            confirmations[identity] = state['mass_confirmations'][vessel['mass_confirmation_id']]
            revisions[identity] = vessel['content_revision']
        return build_cf01_profile(state['definition'], confirmations, revisions, state['logical_time_s'])

    def advance_time(self, actor_id, seconds):
        positive(seconds, 'synthetic elapsed seconds')
        def update(state):
            following = state['logical_time_s'] + seconds
            positive(following, 'resulting process time', zero=True)
            state['logical_time_s'] = following
            stage = state['stages'][state['active_stage']]
            cause = ('workflow_deadline_exceeded' if following >= state['deadline_s'] else
                     'stage_deadline_exceeded' if stage['deadline_s'] is not None and following >= stage['deadline_s'] else None)
            if cause:
                state['recovery_required'] = state['recovery_required'] or cause
                stage['recovery_required'] = stage['recovery_required'] or cause
                if state['status'] != 'cancelling': state['status'] = 'held'
        return self._transition('time_advanced', actor_id, update, {'seconds': seconds})

    def stage(self, stage_id):
        if stage_id not in ADAPTERS: raise TaskError('Manual stage required')
        return StageHandle(self, stage_id)

    def handover(self, actor_id, observations, workspace_clear, arm_clear, gripper_empty):
        def update(state):
            if state['active_stage'] not in ADAPTERS: raise TaskError('A manual stage is required')
            stage = state['stages'][state['active_stage']]
            if stage['status'] != 'ready' or stage['recovery_required']:
                raise TaskError('A reconciled ready stage is required')
            if workspace_clear is not True or arm_clear is not True or gripper_empty is not True:
                raise ObservationError('Explicit synthetic arm and work-area clearance required')
            self._observations(state, observations)
            stage['workspace_clear'] = True
            stage['handover'] = {'actor_id': actor_id, 'evidence': 'synthetic_operator_confirmation',
                                 'time_s': state['logical_time_s']}
        return self._transition('manual_handover', actor_id, update, {'observations': observations})

    def _next_stage(self, state):
        current = state['active_stage'];index = STAGES.index(current)
        if index == len(STAGES) - 1:
            self._audit(state, completing=True)
            state.update(status='completed', resources=[], session=None, recovery_required=None)
        else:
            state['active_stage'] = STAGES[index + 1]
            stage = state['stages'][state['active_stage']]
            stage.update(status='ready', rack_ready=True, workspace_clear=False)
            state['resources'] = self._resources(state)

    def stage_act(self, stage_id, command, actor_id, artifact=None, **data):
        text(stage_id,'stage id');text(command,'stage command')
        def update(state):
            if state['active_stage'] != stage_id or stage_id not in ADAPTERS:
                raise TaskError('Wrong or inactive stage')
            stage = state['stages'][stage_id]
            allowed = set(state['definition']['stages'][stage_id]['protocol']['steps']) | {
                'take', 'reconcile', 'cancel', 'finish_cancel', 'discard_import', 'check_deadline'}
            allowed -= {'rack_ready', 'workspace_clear', 'advance_time'}
            if command not in allowed: raise TaskError('Unsupported integrated stage command: ' + command)
            if stage['actor_id'] is not None and stage['actor_id'] != actor_id:
                raise TaskError('Stage is held by another actor')
            if command == 'claim' and (not stage.get('handover') or stage['handover']['actor_id'] != actor_id):
                raise TaskError('Explicit handover to this actor is required before claim')
            if stage['recovery_required'] and command not in {'reconcile', 'cancel', 'check_deadline'}:
                raise TaskError('Explicit reconciliation required: ' + stage['recovery_required'])
            if state['recovery_required'] and not stage['recovery_required']:
                recovery_commands={'reconcile','cancel','check_deadline','place','dispose_vessel'}
                if stage['status']=='cancelling': recovery_commands |= {'take','finish_cancel'}
                if command not in recovery_commands:
                    raise TaskError('Root reconciliation hold forbids further work')
            if stage['status'] == 'cancelling' and command not in {'reconcile','take','place','dispose_vessel','finish_cancel','check_deadline'}:
                raise TaskError('Only cancellation reconciliation and return are permitted')
            if state['logical_time_s'] >= state['deadline_s'] and command not in {'reconcile','cancel','finish_cancel','take','place','dispose_vessel','check_deadline'}:
                raise TaskError('Workflow deadline exceeded')
            adapter = ADAPTERS[stage_id](self, state, stage_id);view = adapter.state
            pending_before = copy.deepcopy(adapter._pending(view))
            handler = getattr(adapter, '_' + command)
            arguments = {'artifact': artifact, **data} if command == 'import_results' else {'actor_id': actor_id, **data}
            try: inspect.signature(handler).bind(view, **arguments)
            except TypeError as error: raise TaskError('Invalid stage arguments: ' + str(error)) from error
            result = handler(view, **arguments)
            if result is False: return False
            pending_after = adapter._pending(view)
            if pending_after and pending_before is None:
                if stage_id == 'nanodrop':
                    begin_withdrawal(state, stage_id, pending_after, pending_after['sample_id'], {'kind':'discarded_after_cleanup'})
                elif pending_after['kind'] == 'preparation':
                    prep = stage['preparations'][pending_after['preparation_id']]
                    if prep['kind'] == 'sample':
                        begin_withdrawal(state, stage_id, pending_after, prep['target_id'],
                                         {'kind':'vessel','vessel_id':prep['vessel_id'],'preparation_id':prep['id']})
            if pending_before and pending_before['intent_id'] in state['bookings']:
                booking = state['bookings'][pending_before['intent_id']]
                if booking['outcome'] != 'performed':
                    if pending_after is None:
                        booking.update(outcome='not_performed', actual_volume_ul=0.0, confirmed_at_s=state['logical_time_s'])
                    elif stage['recovery_required'] in {'operation_outcome_unknown','measurement_outcome_unknown'}:
                        booking['outcome'] = 'unknown'
            if command == 'claim':
                for vessel in state['inventory']['vessels'].values():
                    vessel['responsibility'] = {'kind':'actor','actor_id':actor_id}
            state['resources'] = self._resources(state)
            state['recovery_required'] = stage['recovery_required']
            if stage['status'] == 'completed': self._next_stage(state)
            elif stage['status'] == 'cancelled':
                self._audit(state)
                state.update(status='cancelled',resources=[],session=None,recovery_required=None)
            else: state['status'] = 'held' if stage['recovery_required'] else 'cancelling' if stage['status']=='cancelling' else 'running'
            if state['logical_time_s'] >= state['deadline_s'] and state['status'] not in TERMINAL:
                state['recovery_required']='workflow_deadline_exceeded'
                if stage['status']!='cancelling': state['status']='held'
        return self._transition(stage_id + '.' + command, actor_id, update, data, artifact)

    @staticmethod
    def _cf_locations(state, inventory):
        definition=state['definition'];bindings=definition['profile']['bindings']
        capacity=definition['stages']['cf01']['required_capacity']
        if (not isinstance(inventory,dict) or set(inventory)!={'rack','rotor','gripper'}
                or any(not isinstance(inventory[key],list) or len(inventory[key])!=capacity for key in ['rack','rotor'])):
            raise ObservationError('CF01 inventory must match the bound rack and rotor capacity')
        identities=[identity for identity in [*inventory['rack'],*inventory['rotor'],inventory['gripper']]
                    if identity is not None]
        if (any(not isinstance(identity,str) for identity in identities) or len(identities)!=capacity
                or len(set(identities))!=capacity or set(identities)!=set(manifest_samples(state))):
            raise ObservationError('CF01 inventory must contain every original exactly once')
        result = {}
        for index, sample_id in enumerate(inventory['rack']):
            if sample_id is not None:
                result[sample_id] = {'kind':'rack', 'rack_id':state['definition']['rack_instance'],
                                     'place_id':state['definition']['rack_places'][index]['place_id']}
        for index, sample_id in enumerate(inventory['rotor']):
            if sample_id is not None:
                result[sample_id] = {'kind':'rotor','instance_id':bindings['station_instance'],'slot':index+1}
        if inventory['gripper'] is not None:
            result[inventory['gripper']] = {'kind':'gripper','instance_id':bindings['arm_instance']}
        if set(result) != set(manifest_samples(state)):
            raise ObservationError('CF01 inventory does not conserve the manifest samples')
        return result

    def _cf_checkpoint(self, kind, payload, view):
        def update(state):
            if state['active_stage'] != 'cf01': raise TaskError('Inactive CF01 checkpoint')
            stage = state['stages']['cf01']
            if kind in {'command_intent','handoff_intent'} and payload.get('command') != 'stop':
                if state['status'] in {'held','cancelling'} or state['recovery_required'] or stage['status'] != 'working':
                    raise ProcessHold('CF01 is held; no new side effects are permitted')
            converted = copy.deepcopy(view)
            samples = manifest_samples(state)
            for field in ['inventory','world_inventory']:
                locations = self._cf_locations(state, view[field])
                for sample_id, location in locations.items():
                    vessel = state['inventory']['vessels'][samples[sample_id]['vessel_id']]
                    if field == 'inventory':
                        vessel['location'] = location
                        if location == original_location(state,sample_id):
                            if view['pending_handoff'] is None:
                                vessel['return_confirmation'] = {'actor_id':'SYN.CF01.Driver','evidence':'synthetic_input'}
                        else: vessel['return_confirmation'] = None
                        vessel['responsibility'] = ({'kind':'workflow','run_id':self.run_id}
                            if location['kind']=='rack' else {'kind':'device','instance_id':
                            location['instance_id']})
                    else:
                        vessel['observed_location'] = {'location':location,'time_s':state['logical_time_s'],
                                                       'evidence':'synthetic_robot_observation'}
                inv = converted[field]
                inv['rack'] = [samples[s]['vessel_id'] if s is not None else None for s in inv['rack']]
                inv['rotor'] = [samples[s]['vessel_id'] if s is not None else None for s in inv['rotor']]
                inv['gripper'] = samples[inv['gripper']]['vessel_id'] if inv['gripper'] is not None else None
            if converted['pending_handoff']:
                converted['pending_handoff']['vessel_id'] = samples[converted['pending_handoff']['sample_id']]['vessel_id']
            stage['view'] = converted
            if kind == 'command_intent':
                if stage['pending_command']:
                    stage['unresolved_command'] = stage['pending_command']
                stage['pending_command'] = copy.deepcopy(payload)
            elif kind in {'command_completed','stop_accepted'}:
                stage['pending_command'] = None
            elif kind == 'failed':
                stage.update(status='held', recovery_required=stage['recovery_required'] or 'cf01_failure')
                state.update(status='held', recovery_required=state['recovery_required'] or 'cf01_failure')
        return self._transition('cf01.'+kind, 'SYN.CF01.Driver', update, payload)

    def _advance_cf_clock(self, seconds):
        state = self.advance_time('SYN.CF01.Driver', seconds)
        if state['recovery_required'] or state['status'] != 'running':
            raise ProcessHold('CF01 process deadline or reconciliation hold reached')

    def _advance_cf_hold_clock(self, seconds):
        state=self.state
        if state['active_stage']!='cf01' or state['status'] not in {'held','cancelling'}:
            raise TaskError('CF01 stop observation requires a held or cancelling CF01 stage')
        self.advance_time('SYN.CF01.Driver',seconds)

    def run_cf01(self, actor_id, transport='ros2', configure=None):
        if transport not in {'ros2','sila2'}: raise TaskError('Local decoder must be ros2 or sila2')
        def start(state):
            stage=state['stages']['cf01']
            if state['active_stage']!='cf01' or stage['status']!='ready' or state['recovery_required']:
                raise TaskError('CF01 requires a reconciled initial stage; interrupted jobs cannot resume')
            self._observations(state, self.inventory_observations())
            self.cf01_profile(state)
            stage.update(status='working',actor_id=actor_id,deadline_s=state['deadline_s'],transport=transport)
        self._transition('cf01.stage_started',actor_id,start,{'transport':transport})
        runner=Runner(self.cf01_profile(self.state), transport=transport,
                      clock=lambda:self.state['logical_time_s'],
                      advance_clock=self._advance_cf_clock,
                      advance_hold_clock=self._advance_cf_hold_clock,
                      checkpoint=self._cf_checkpoint)
        if configure is not None: configure(runner)
        try:
            report=runner.run()
        except BatchError as error:
            artifact=encoded(error.report).encode()
            def fail(state):
                state['stages']['cf01'].update(status='held',recovery_required=state['stages']['cf01']['recovery_required'] or 'cf01_failure',
                                               report_artifact_sha256=digest(artifact))
                state.update(status='held', recovery_required=state['recovery_required'] or 'cf01_failure')
            self._transition('cf01.stage_failed',actor_id,fail,{'error':str(error)},artifact)
            raise
        # Storage failures intentionally propagate. The persisted active attempt
        # is held by open(); neither a new Simulator nor success is fabricated.
        artifact=encoded(report).encode()
        def finish(state):
            if state['recovery_required'] or not report['passed'] or not report['order_restored']:
                raise TaskError('CF01 is held or incomplete')
            stage=state['stages']['cf01'];view=stage['view']
            station=view['station']
            if (view['pending_handoff'] is not None or view['ownership']!='confirmed'
                    or any(view['inventory']['rotor']) or view['inventory']['gripper'] is not None
                    or station['standstill_confirmed'] is not True or station['parking_brake_held'] is not True):
                raise TaskError('Confirmed empty, stopped CF01 and restored originals required')
            self._observations(state,self.inventory_observations())
            stage.update(status='completed', report_artifact_sha256=digest(artifact))
            self._next_stage(state)
        self._transition('cf01.stage_completed',actor_id,finish,{'artifact_sha256':digest(artifact)},artifact)
        return report

    def cancel(self, actor_id, reason):
        text(reason,'cancellation reason')
        if self.state['active_stage'] in ADAPTERS:
            return self.stage_act(self.state['active_stage'],'cancel',actor_id,reason=reason)
        def update(state):
            state.update(status='cancelling',cancel_reason=reason,recovery_required='cf01_abort_inventory_check')
            state['stages']['cf01'].update(status='cancelling',recovery_required='cf01_abort_inventory_check')
        return self._transition('cf01.abort_requested',actor_id,update,{'reason':reason})

    def finish_cf01_abort(self, actor_id, observations, rotor_empty, gripper_empty,
                          standstill_confirmed, parking_brake_held, lift_parked,
                          arm_clear, workspace_clear, retire_attempt, reason,
                          evidence='synthetic_operator_confirmation'):
        text(reason,'abort reconciliation reason')
        def update(state):
            if state['active_stage']!='cf01' or state['status']!='cancelling':
                raise TaskError('An explicitly requested CF01 cancellation is required')
            if evidence!='synthetic_operator_confirmation':
                raise TaskError('CF01 abort evidence must be explicitly synthetic operator input')
            if (not isinstance(rotor_empty,list) or any(type(slot) is not int for slot in rotor_empty)
                    or rotor_empty != list(range(1,state['definition']['stages']['cf01']['required_capacity']+1))):
                raise ObservationError('Explicit empty observation for all twelve rotor places required')
            if any(flag is not True for flag in [gripper_empty,standstill_confirmed,parking_brake_held,
                                                lift_parked,arm_clear,workspace_clear,retire_attempt]):
                raise ObservationError('Complete synthetic stop, clearance and attempt retirement required')
            locations=self._observations(state,observations)
            for identity,location in locations.items():
                vessel=state['inventory']['vessels'][identity]
                vessel['location']=location
                vessel['observed_location']={'location':location,'time_s':state['logical_time_s'],'evidence':evidence}
                vessel['return_confirmation']={'actor_id':actor_id,'evidence':evidence}
            state['stages']['cf01'].update(status='cancelled',recovery_required=None,
                abort_reconciliation={'actor_id':actor_id,'reason':reason,'evidence':evidence,
                                      'rotor_empty':rotor_empty,'retired_attempt':True,
                                      'gripper_empty':gripper_empty,'standstill_confirmed':standstill_confirmed,
                                      'parking_brake_held':parking_brake_held,'lift_parked':lift_parked,
                                      'arm_clear':arm_clear,'workspace_clear':workspace_clear,
                                      'time_s':state['logical_time_s']})
            stage=state['stages']['cf01']
            stage['retired_execution']={'view':stage['view'],'pending_command':stage['pending_command'],
                                         'unresolved_command':stage.get('unresolved_command')}
            stage.update(view=None,pending_command=None)
            stage.pop('unresolved_command',None)
            self._audit(state)
            state.update(status='cancelled',recovery_required=None,resources=[],session=None)
        return self._transition('cf01.abort_reconciled',actor_id,update,
                                {'observations':observations,'reason':reason,'evidence':evidence})

    def _audit(self, state, completing=False):
        self.journal.history(self.run_id)
        for stage in state['stages'].values():
            for checksum,record in stage.get('imports',{}).items():
                if len(self.journal.artifact(checksum)) != record['byte_count']:
                    raise TaskError('Stage artifact byte count mismatch')
            if stage.get('report_artifact_sha256'):
                self.journal.artifact(stage['report_artifact_sha256'])
        if completing:
            if any(stage['status']!='completed' for stage in state['stages'].values()):
                raise TaskError('Every stage must be explicitly completed')
            if any(b['outcome'] in {'intent','unknown'} for b in state['bookings'].values()):
                raise TaskError('Unresolved consumption blocks final completion')
            self._observations(state,[{'vessel_id':identity,'location':v['location'],
                **({'sample_id':v['sample_id']} if v['origin']=='original' else {})}
                for identity,v in state['inventory']['vessels'].items()])

    def report(self):
        trace=self.journal.history(self.run_id)
        state=trace[-1]['state'];self._format(state)
        for stage in state['stages'].values():
            for checksum in stage.get('imports',{}):self.journal.artifact(checksum)
            if stage.get('report_artifact_sha256'):self.journal.artifact(stage['report_artifact_sha256'])
        samples={}
        for sample_id,sample in manifest_samples(state).items():
            vessel=state['inventory']['vessels'][sample['vessel_id']]
            samples[sample_id]={**sample,'location':vessel['location'],
                'remaining_volume_ul':None if vessel['volume_uncertain'] else remaining(state,sample_id),
                'initial_volume_source':'integrated_manifest_once',
                'withdrawn_volume_ul':sum(b['actual_volume_ul'] for b in state['bookings'].values()
                    if b['sample_id']==sample_id and b['outcome']=='performed'),
                'content_revision':vessel['content_revision'],
                'mass_confirmation_valid':vessel['mass_confirmation_valid']}
        cf_view=state['stages']['cf01']['view']
        cf_resolved=(cf_view is None or (cf_view['pending_handoff'] is None and cf_view['ownership']=='confirmed'))
        return {'format':'solidcraftbot.synthetic-lab-report/1','run_id':self.run_id,
            'passed':state['status']=='completed','status':state['status'],'active_stage':state['active_stage'],
            'clock_mode':state['clock_mode'],'logical_time_s':state['logical_time_s'],
            'samples':samples,'inventory':state['inventory'],'bookings':state['bookings'],
            'stages':state['stages'],'mass_confirmations':state['mass_confirmations'],
            'resources':state['resources'],'recovery_required':state['recovery_required'],
            'order_restored':cf_resolved and all(v['location']==original_location(state,s['sample_id']) and v['return_confirmation']
                for s in state['definition']['manifest']['samples']
                for v in [state['inventory']['vessels'][s['vessel_id']]]),
            'source_files_sha256':state['definition']['source_files_sha256'],
            'effective_profile_sha256':state['definition']['effective_profile_sha256'],
            'event_count':len(trace),'last_event_sha256':trace[-1]['sha256'],
            'mode':'synthetic_only','network_executed':False,'hardware_executed':False,
            'robot_motion_executed':False,'calibration_curve_computed':False,'real_export_validated':False,
            'cross_run_volume_ledger':False,'active_cf01_job_resume_supported':False,
            'limitations':['All inputs, SOPs, masses, timing and results are synthetic',
                'Manual work-area and CF01 abort confirmations are not safety functions',
                'CF01 observations use mock internals; no physical identity sensor',
                'No network, hardware, new CAD geometry or executed robot paths',
                'No reagent stock ledger or automatic inventory carryover between root runs',
                'Interrupted CF01 attempts require explicit abort inventory reconciliation']}
