"""Manual E4 evidence capture on the shared journal and material ledger.

This first contract records declared human observations and opaque original QC
files. It neither operates equipment nor certifies a SOP, clock or assay. Open
laboratory bindings gate new intents, never the preservation of observations.
"""
import copy
from datetime import datetime, timezone
import uuid

import material_evidence
import material_ledger as ledger
import manual_process_clock as process_clock
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, ManualWorkflow, ObservationError, keys, text
from material_workflow import MaterialWorkflow


def utc(value):
    if not isinstance(value, str):
        raise TaskError('Explicit timezone-aware observation time required')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise TaskError('Invalid observation time') from error
    if result.tzinfo is None:
        raise TaskError('Naive observation time is not evidence')
    return result.astimezone(timezone.utc)


class CutRunManualWorkflow(MaterialWorkflow):
    ENGINE = 'cutrun_manual_capture/1'
    MATERIAL_STAGES = frozenset({'S02', 'S03', 'S04', 'S05', 'S09', 'S10'})
    STATE_FORMAT = 'solidcraftbot.material-workflow-state/3'
    REPORT_FORMAT = 'solidcraftbot.cutrun-manual-report/1'
    STEPS = ('accept_inventory', 'confirm_inventory', 'workspace_clear', 'claim',
             'record_observation', 'begin_material_action', 'confirm_material_action',
             'begin_activation', 'begin_stop', 'confirm_dose', 'confirm_stop_mixing',
             'record_external_activation', 'record_external_stop', 'begin_qc_withdrawal',
             'mark_unknown', 'resolve_action', 'resolve_clock_gap', 'check_clock',
             'attach_qc', 'import_results', 'map_qc', 'review_qc', 'review_biology',
             'clarify_qc', 'resolve_deviation', 'set_disposition', 'resolve_quantity',
             'abnormal_termination', 'close_capture')
    RECOVERY_COMMANDS = {'record_observation', 'begin_stop', 'confirm_dose', 'confirm_stop_mixing',
                        'record_external_activation', 'record_external_stop',
                        'mark_unknown', 'resolve_action', 'resolve_clock_gap', 'check_clock',
                        'attach_qc', 'import_results', 'map_qc', 'review_qc', 'review_biology',
                        'clarify_qc', 'resolve_deviation', 'reconcile',
                        'set_disposition', 'resolve_quantity', 'abnormal_termination', 'cancel', 'finish_cancel'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    def __init__(self, journal, run_id, session, *, clock=None):
        super().__init__(journal, run_id, session)
        self.clock_provider = process_clock.SystemClock() if clock is None else clock
        self._observation = None
        self._fingerprint = None
        if session is not None:
            self._verify_runtime(self.state)
            self._verify_initial_artifacts(self.journal, self.state)

    @classmethod
    def _validate_format(cls, state):
        super()._validate_format(state)
        definition = state.get('definition', {})
        if (definition.get('format') != 'solidcraftbot.material-workflow-definition/3'
                or definition.get('profile', {}).get('type') != cls.ENGINE
                or state.get('manual', {}).get('engine') != cls.ENGINE):
            raise TaskError('Matching manual /3 definition and capture engine required')

    @staticmethod
    def _verify_runtime(state):
        definition = state['definition']
        names = definition.get('runtime_source_files')
        if not names:
            raise TaskError('Manual runtime source manifest required')
        for name in names:
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file() or digest(path.read_bytes()) != definition['source_files_sha256'].get(name):
                raise TaskError('Runtime source changed; inspect the pinned run before migration: ' + name)

    @staticmethod
    def _verify_initial_artifacts(journal, state):
        definition = state['definition']
        manifest = definition.get('initial_artifact_sha256')
        if not isinstance(manifest, list) or not manifest or len(manifest) != len(set(manifest)):
            raise TaskError('Pinned original source artifact manifest required')
        for checksum in manifest:
            journal.artifact(checksum)
        for record in definition['evidence_records'].values():
            if record['sha256'] not in manifest or len(journal.artifact(record['sha256'])) != record['size_bytes']:
                raise TaskError('Decision evidence original is missing or changed')
        profile = definition['manual_profile']
        required = [profile['sources']['sop']['source_sha256']]
        if definition['original_pdf_verified']:
            required.append(profile['sources']['manufacturer']['source_sha256'])
        if any(checksum not in manifest for checksum in required):
            raise TaskError('Bound source original missing from artifact manifest')

    def _audit_artifacts(self, trace):
        super()._audit_artifacts(trace)
        self._verify_initial_artifacts(self.journal, trace[-1]['state'])

    @classmethod
    def _clock_matches(cls, journal, state, clock_mode=None):
        if state['definition'].get('clock_mode') != 'real_observations/1' or clock_mode not in (None, 'real_observations/1'):
            raise TaskError('Manual real-observation clock contract required')

    @classmethod
    def _load_definition(cls, source, **kwargs):
        from cutrun_manual_sources import load
        return load(source, **kwargs)

    @classmethod
    def _extra_state(cls, definition, reactions):
        return {}

    @classmethod
    def _validate_reagent_binding(cls, inventory, source, reaction_id, item, key):
        reagent = inventory['materials'].get(item[key])
        if reagent is None or reagent['kind'] != 'reagent':
            raise TaskError('Distinct issued activation and stop aliquots required per reaction')

    @classmethod
    def create(cls, journal, source=None, *, materials, vessels, reactions, actors,
               run_id=None, clock=None, original_pdf=None, evidence_files=None):
        provider = process_clock.SystemClock() if clock is None else clock
        sample = process_clock.validate_sample(provider.sample())
        if not isinstance(actors, list) or not actors or any(not isinstance(actor, str) or not actor.strip() for actor in actors) or len(set(actors)) != len(actors):
            raise TaskError('Explicit attributable operator identifiers required; they are not authentication')
        inventory = ledger.initial_inventory(materials, vessels)
        if not isinstance(reactions, dict):
            raise TaskError('Explicit reaction bindings required')
        bindings, declared, stop_ids, used_vessels, used_roles, used_materials = {}, {}, set(), set(), set(), set()
        for reaction_id, item in reactions.items():
            text(reaction_id, 'reaction identity')
            keys(item, 'role material_id vessel_id activation_material_id stop_material_id', 'manual reaction binding')
            if item['role'] not in {'h3k4me3', 'igg', 'input'} or item['role'] in used_roles or item['material_id'] in used_materials:
                raise TaskError('One uniquely identified reaction per declared role required')
            used_roles.add(item['role']);used_materials.add(item['material_id'])
            material = inventory['materials'].get(item['material_id'])
            target = item['vessel_id']
            if (material is None or material['kind'] not in {'sample', 'control'} or target not in inventory['vessels']
                    or material['vessel_id'] != target
                    or target in used_vessels or any(value['vessel_id'] == target and value['id'] != material['id']
                                                   for value in inventory['materials'].values())):
                raise TaskError('Reaction needs its own identified material and actual vessel')
            used_vessels.add(item['vessel_id'])
            if item['role'] == 'input':
                if item['activation_material_id'] is not None or item['stop_material_id'] is not None:
                    raise TaskError('Input is not an activation branch')
            else:
                for key in ('activation_material_id', 'stop_material_id'):
                    cls._validate_reagent_binding(inventory, source, reaction_id, item, key)
                    if item[key] in stop_ids:
                        raise TaskError('Distinct issued activation and stop aliquots required per reaction')
                    stop_ids.add(item[key])
                bindings[item['vessel_id']] = item['stop_material_id']
            declared[reaction_id] = {**copy.deepcopy(item), 'current_material_id': item['material_id'],
                'status': 'inactive', 'activation': None, 'stop': None}
        definition = cls._load_definition(source, materials=materials, vessels=vessels,
                          clock_source_kind=sample['source_kind'], original_pdf=original_pdf,
                          evidence_files=evidence_files, protective_stop_bindings=bindings)
        artifacts = definition.pop('_initial_artifacts', None)
        definition['initial_artifact_sha256'] = sorted(artifacts or {})
        for item in reactions.values():
            role = definition['manual_profile']['roles'][item['role']]
            if any(role[key] is not None and role[key] != item[key] for key in ('material_id', 'vessel_id')):
                raise TaskError('Actual reaction binding differs from the pinned SOP role')
        definition['manual_actors'] = copy.deepcopy(actors)
        definition['reaction_bindings'] = copy.deepcopy(reactions)
        definition['effective_profile_sha256'] = digest(encoded({
            'source': definition['effective_profile_sha256'], 'actors': actors, 'reactions': reactions}).encode())
        identity = run_id or 'MANUAL.CUTRUN.' + uuid.uuid4().hex[:12]
        if identity.startswith('SYN.'):
            raise TaskError('A manual run must not reuse a synthetic fixture identity')
        flow = cls._create_definition(journal, definition, run_id=identity, extra_state={
            'clock': process_clock.initial(sample), 'observation_context': None,
            'protective_operations': {}, 'manual': {
                'engine': cls.ENGINE, 'reactions': declared, 'actions': {},
                'observations': {}, 'stage_observations': [], 'qc_artifacts': {},
                'qc_bindings': {}, 'qc_reviews': {}, 'biology_reviews': {}, 'holds': []},
            **cls._extra_state(definition, declared)},
            initial_artifacts=artifacts)
        flow.clock_provider = provider
        return flow

    @classmethod
    def open(cls, journal, run_id, resume=False, *, clock=None, clock_mode=None):
        state, revision = journal.state(run_id)
        cls._validate_format(state); cls._clock_matches(journal, state, clock_mode)
        if state['status'] in {'completed', 'cancelled'}:
            return cls(journal, run_id, None, clock=clock)
        cls._verify_runtime(state)
        cls._verify_initial_artifacts(journal, state)
        if state['session'] is not None and not resume:
            raise TaskError('Explicit resume required for the previous manual session')
        provider = process_clock.SystemClock() if clock is None else clock
        sample = process_clock.validate_sample(provider.sample())
        if sample['source_kind'] != state['definition']['clock_source_kind']:
            raise TaskError('Clock source kind cannot switch between real and test clocks')
        state['clock'] = process_clock.refresh(state['clock'], sample)
        state['logical_time_s'] = state['clock']['lower_s']
        state['session'] = uuid.uuid4().hex
        state['recovery_required'], state['workspace_clear'] = 'manual_session_restarted', False
        journal.append(run_id, revision, 'manual_session_opened',
                       {'explicit_resume': resume, 'recorded_at': sample,
                        'evidence': 'clock_observation', 'no_effect_replayed': True}, state)
        return cls(journal, run_id, state['session'], clock=provider)

    def _before_transition(self, state):
        if self._observation is None:
            raise TaskError('A stable observation envelope is required')
        sample = process_clock.validate_sample(self.clock_provider.sample())
        if sample['source_kind'] != state['definition']['clock_source_kind']:
            raise TaskError('Clock source kind changed')
        state['clock'] = process_clock.refresh(state['clock'], sample)
        state['logical_time_s'] = state['clock']['lower_s']
        state['observation_context'] = copy.deepcopy(self._observation)
        if state['clock']['gap_required']:
            state['recovery_required'], state['workspace_clear'] = 'unresolved_clock_gap', False
        self._evaluate_reactions(state)

    def _event_evidence(self, state, command, actor_id, data):
        return {**material_evidence.provenance(state), 'recorded_at': copy.deepcopy(state['clock']['last_sample'])}

    def _deadline_event(self, state):
        clock_state = copy.deepcopy(state)
        clock_state['observation_context'] = None
        return ({'evidence': 'clock_observation', 'recorded_at': copy.deepcopy(state['clock']['last_sample'])}, clock_state)

    def _after_transition(self, state, command, actor_id, data, *, rejected=False):
        state['manual']['observations'][self._observation['observation_id']] = self._fingerprint

    @staticmethod
    def _authorize_actor(state, command, actor_id):
        if actor_id not in state['definition']['manual_actors']:
            raise TaskError('Actor is not declared for this manual record')
        if state['actor_id'] is not None and state['actor_id'] != actor_id and command not in {
                'record_observation', 'begin_stop', 'confirm_dose', 'confirm_stop_mixing',
                'record_external_stop',
                'check_clock', 'resolve_clock_gap', 'attach_qc', 'import_results'}:
            raise TaskError('Ordinary work remains assigned to the claimed operator')

    def _claim(self, state, actor_id):
        if state['status'] != 'ready' or not state['workspace_clear'] or state['actor_id']:
            raise TaskError('Accepted inventory and work-area observation required')
        state['actor_id'], state['status'], state['workspace_clear'] = actor_id, 'working', False
        value = self._parameter(state, 'task_deadline_s')
        state['deadline_s'] = None if value is None else state['clock']['lower_s'] + value
        self._assign_responsibility(state, actor_id)

    @staticmethod
    def _parameter(state, name):
        record = state['definition']['manual_profile']['parameters'].get(name)
        return None if record is None else record['value']

    def _stage_ready(self, state, stage_id):
        self._claimed(state)
        if state['status'] != 'working' or state['recovery_required']:
            raise TaskError('Reconciled working manual record required for a new intent')
        if not state['definition']['stage_readiness'].get(stage_id, False):
            raise TaskError('Open SOP bindings block stage ' + str(stage_id))
        if any(item['outcome'] in {'intent', 'unknown'} for item in state['bookings'].values()):
            raise TaskError('Resolve open material effects before ordinary work')

    @staticmethod
    def _reaction(state, reaction_id):
        value = state['manual']['reactions'].get(reaction_id)
        if value is None:
            raise ObservationError('Unknown actual reaction identity')
        return value

    @staticmethod
    def _hold(state, code, reason):
        if not any(item['code'] == code and item['reason'] == reason and 'resolution' not in item
                   for item in state['manual']['holds']):
            state['manual']['holds'].append({'code': code, 'reason': reason,
                **material_evidence.provenance(state)})
        state['recovery_required'], state['workspace_clear'] = code, False

    def _evaluate_reactions(self, state):
        for identity, reaction in state['manual']['reactions'].items():
            activation = reaction['activation']
            if activation and reaction['status'] in {'possibly_active', 'active', 'stop_unconfirmed'}:
                deadline = activation.get('stop_deadline_lower_s')
                upper = state['clock']['upper_s']
                if deadline is not None and (upper is None or upper > deadline):
                    self._hold(state, 'reaction_time_uncertain', 'Stop deadline cannot be established for ' + identity)

    def _record_observation(self, state, actor_id, stage_id, reaction_id, status, details):
        if stage_id not in state['definition']['stage_readiness']:
            raise TaskError('Unknown SOP stage')
        if reaction_id is not None:
            self._reaction(state, reaction_id)
        if status not in {'observed', 'unknown', 'not_performed'} or not isinstance(details, dict):
            raise TaskError('Explicit observation status and details required')
        encoded(details)
        state['manual']['stage_observations'].append({'stage_id': stage_id, 'reaction_id': reaction_id,
            'status': status, 'details': copy.deepcopy(details), 'actor_id': actor_id,
            **material_evidence.provenance(state)})

    def _begin_material_action(self, state, actor_id, intent_id, reaction_id, stage_id, kind, inputs, outputs, purpose,
                               retained_material_id=None):
        if stage_id not in self.MATERIAL_STAGES:
            raise TaskError('Use the dedicated activation, stop or QC operation')
        self._stage_ready(state, stage_id)
        reaction = self._reaction(state, reaction_id)
        if reaction['status'] not in {'inactive', 'stopped'}:
            raise TaskError('Ordinary material handling cannot bypass the reaction stop path')
        reserved = {value for item in state['manual']['reactions'].values()
                    for value in (item['activation_material_id'], item['stop_material_id']) if value is not None}
        if not isinstance(inputs, list) or any(item.get('material_id') in reserved for item in inputs if isinstance(item, dict)):
            raise TaskError('Issued activation/stop aliquots cannot be spent through a generic action')
        for item in inputs:
            material = state['inventory']['materials'].get(item.get('material_id')) if isinstance(item, dict) else None
            if material is None or (material['kind'] != 'reagent' and item['material_id'] != reaction['current_material_id']):
                raise TaskError('Material inputs must belong to this reaction or an issued reagent')
        if not any(item['material_id'] == reaction['current_material_id'] for item in inputs):
            raise TaskError('A reaction-bound material action must retain the sample lineage')
        if not isinstance(outputs, list):
            raise TaskError('Explicit output declarations required')
        retained = [item['material_id'] for item in outputs if isinstance(item, dict) and item.get('kind') in {'product', 'intermediate'}]
        if retained_material_id is None and len(retained) == 1:
            retained_material_id = retained[0]
        if (len(retained) > 1 and retained_material_id is None
                or retained_material_id is not None and retained_material_id not in retained):
            raise TaskError('Explicit unambiguous retained reaction fraction required')
        changed = ledger.begin_effect(state, actor_id, intent_id, kind, inputs, outputs, purpose)
        if changed is False:
            old = state['manual']['actions'].get(intent_id, {})
            if any(old.get(key) != value for key, value in {'operation': 'material', 'stage_id': stage_id,
                    'reaction_id': reaction_id, 'retained_material_id': retained_material_id}.items()):
                raise TaskError('Existing intent metadata cannot change')
            return False
        state['manual']['actions'][intent_id] = {'operation': 'material', 'stage_id': stage_id,
            'reaction_id': reaction_id, 'retained_material_id': retained_material_id,
            'recorded_intent_at': copy.deepcopy(state['clock']['last_sample'])}
        self._after_material_change(state, True)

    def _confirm_material_action(self, state, actor_id, intent_id, actual_inputs, actual_outputs, reason):
        action = state['manual']['actions'].get(intent_id)
        if not action or action['operation'] not in {'material', 'qc_withdrawal'}:
            raise TaskError('Matching manual material intent required')
        changed = ledger.confirm_effect(state, actor_id, intent_id, actual_inputs, actual_outputs, reason)
        if changed is False:
            return False
        action = state['manual']['actions'][intent_id]
        if action.get('retained_material_id') is not None:
            state['manual']['reactions'][action['reaction_id']]['current_material_id'] = action['retained_material_id']
        return self._after_material_change(state, True)

    def _begin_activation(self, state, actor_id, intent_id, reaction_id, stop_access, mixing_available):
        self._stage_ready(state, 'S07')
        reaction = self._reaction(state, reaction_id)
        if reaction['role'] == 'input' or reaction['status'] != 'inactive' or reaction['activation'] is not None:
            raise TaskError('Only an inactive CUT&RUN reaction may activate')
        if stop_access is not True or mixing_available is not True:
            raise ObservationError('Current actual stop access and mixing readiness required')
        if any(item['status'] in {'possibly_active', 'active', 'stop_unconfirmed'} for item in state['manual']['reactions'].values()):
            raise TaskError('The manual first contract is serial: stop the previous reaction first')
        if state['clock']['gap_required'] or state['clock']['upper_s'] is None:
            raise TaskError('Bounded qualified process time is required before activation')
        dose, stop_dose = self._parameter(state, 'activation_volume_ul'), self._parameter(state, 'stop_volume_ul')
        duration, window = self._parameter(state, 'activation_duration_s'), self._parameter(state, 'stop_window_s')
        if any(value is None for value in (dose, stop_dose, duration, window)):
            raise TaskError('No activation/stop dose or time default is inferred')
        balance = ledger.remaining(state, reaction['stop_material_id'])
        stop_material = state['inventory']['materials'][reaction['stop_material_id']]
        if (balance['value'] is None or balance['value'] < stop_dose or stop_material['vessel_id'] is None
                or stop_material['disposition'] in {'consumed', 'discarded', 'quarantined'}):
            raise TaskError('Known sufficient separately issued stop material required')
        if state['inventory']['materials'][reaction['current_material_id']]['vessel_id'] != reaction['vessel_id']:
            raise ObservationError('Current reaction material is not in its bound reaction vessel')
        ledger.begin_effect(state, actor_id, intent_id, 'withdrawal',
            [{'material_id': reaction['activation_material_id'], 'quantity': {'value': dose, 'unit': 'uL'}, 'consume_all': False}],
            [], 'manual_activation')
        reaction = state['manual']['reactions'][reaction_id]
        reaction['status'] = 'possibly_active'
        reaction['activation'] = {'intent_id': intent_id, 'start_lower_s': state['clock']['lower_s'],
            'stop_deadline_lower_s': state['clock']['lower_s'] + duration + window}
        state['manual']['actions'][intent_id] = {'operation': 'activation', 'reaction_id': reaction_id,
            'recorded_intent_at': copy.deepcopy(state['clock']['last_sample'])}
        self._after_material_change(state, True)

    def _begin_stop(self, state, actor_id, intent_id, reaction_id, stop_access, mixing_available):
        self._claimed(state)
        reaction = self._reaction(state, reaction_id)
        if reaction['activation'] is None or reaction['role'] == 'input':
            raise TaskError('A possibly active reaction is required')
        if stop_access is not True or mixing_available is not True:
            self._hold(state, 'stop_path_blocked', 'Observed stop access/mixing is unavailable for ' + reaction_id)
            return
        dose = self._parameter(state, 'stop_volume_ul')
        if dose is None:
            self._hold(state, 'stop_binding_open', 'No new stop instruction inferred from an open dose')
            return
        changed = ledger.begin_protective_stop(state, actor_id, intent_id, reaction['vessel_id'],
                                               reaction['stop_material_id'], {'value': dose, 'unit': 'uL'})
        if changed is False:
            return False
        state['manual']['actions'][intent_id] = {'operation': 'stop', 'reaction_id': reaction_id,
            'retrospective': False, 'recorded_intent_at': copy.deepcopy(state['clock']['last_sample'])}
        self._after_material_change(state, True)

    def _confirm_dose(self, state, actor_id, intent_id, actual_volume_ul, mixed, reason):
        action = state['manual']['actions'].get(intent_id)
        if not action or action['operation'] not in {'activation', 'stop'}:
            raise TaskError('Matching dose intent required')
        if type(mixed) is not bool:
            raise TaskError('Explicit mixing observation required')
        quantity = ledger.quantity({'value': actual_volume_ul, 'unit': 'uL'})
        reaction = state['manual']['reactions'][action['reaction_id']]
        kind = action['operation']
        actual = [{'material_id': reaction['activation_material_id'] if kind == 'activation' else reaction['stop_material_id'], 'quantity': quantity}]
        changed = (ledger.confirm_effect(state, actor_id, intent_id, actual, [], reason) if kind == 'activation'
                   else ledger.confirm_protective_stop(state, actor_id, intent_id, actual, reason))
        if changed is False:
            return False
        action = state['manual']['actions'][intent_id]
        action['mixing_confirmed'] = mixed
        reaction = state['manual']['reactions'][action['reaction_id']]
        if kind == 'activation':
            reaction['activation']['contact_upper_s'] = state['clock']['upper_s']
            if reaction['status'] != 'stopped':
                reaction['status'] = 'active' if mixed else 'possibly_active'
        else:
            required = self._parameter(state, 'stop_volume_ul')
            reaction['stop'] = {'intent_id': intent_id, 'observed_at': copy.deepcopy(state['observation_context']['observed_at']),
                                'mixed': mixed, 'actual_volume_ul': actual_volume_ul,
                                'recorded_clock': copy.deepcopy(state['clock']), 'mixing_receipt': None}
            reaction['status'] = 'stopped' if mixed and required is not None and actual_volume_ul is not None and actual_volume_ul >= required else 'stop_unconfirmed'
        if not mixed or actual_volume_ul is None or reaction['status'] == 'stop_unconfirmed':
            self._hold(state, 'dose_or_mixing_uncertain', 'Dose/mixing requires assessment for ' + action['reaction_id'])
        self._after_material_change(state, True)

    def _confirm_stop_mixing(self, state, actor_id, intent_id, mixed, reason):
        action = state['manual']['actions'].get(intent_id)
        if action is None or action['operation'] != 'stop':
            raise TaskError('A confirmed stop dose is required')
        reaction = state['manual']['reactions'][action['reaction_id']]
        stop = reaction['stop']
        if stop is None or stop['mixed'] or stop['mixing_receipt'] is not None:
            raise TaskError('No pending mixing-only stop observation; first stop evidence is immutable')
        if mixed is not True:
            raise ObservationError('Mixing is still unconfirmed')
        required = self._parameter(state, 'stop_volume_ul')
        if required is None or stop['actual_volume_ul'] is None or stop['actual_volume_ul'] < required:
            raise TaskError('Mixing cannot prove an unknown or insufficient stop dose')
        stop['mixed'] = True
        stop['mixing_receipt'] = material_evidence.receipt(state, actor_id, reason)
        stop['mixing_observed_at'] = copy.deepcopy(state['observation_context']['observed_at'])
        stop['recorded_clock'] = copy.deepcopy(state['clock'])
        reaction['status'] = 'stopped'

    def _record_external_activation(self, state, actor_id, reaction_id, actual_volume_ul, mixed, reason):
        if state['observation_context']['source_kind'] not in {'external_record', 'test_fixture'}:
            raise TaskError('Retrospective action provenance required')
        reaction = self._reaction(state, reaction_id)
        if reaction['role'] == 'input':
            raise TaskError('Input has no CUT&RUN activation role')
        if reaction['activation'] is not None:
            identity = reaction['activation']['intent_id']
        else:
            identity = 'EXTERNAL.' + state['observation_context']['observation_id']
            ledger.begin_effect(state, actor_id, identity, 'withdrawal',
                [{'material_id': reaction['activation_material_id'], 'quantity': {'value': actual_volume_ul, 'unit': 'uL'}, 'consume_all': False}],
                [], 'retrospective_external_activation_not_a_prior_electronic_intent')
            reaction = state['manual']['reactions'][reaction_id]
            reaction['activation'] = {'intent_id': identity, 'start_lower_s': None,
                                      'stop_deadline_lower_s': None, 'contact_upper_s': None}
            reaction['status'] = 'possibly_active'
            state['manual']['actions'][identity] = {'operation': 'activation', 'reaction_id': reaction_id,
                'retrospective': True, 'recorded_intent_at': copy.deepcopy(state['clock']['last_sample'])}
        self._confirm_dose(state, actor_id, identity, actual_volume_ul, mixed, reason)
        self._hold(state, 'external_activation_needs_assessment', 'Retrospective activation time/quantity requires explicit assessment')

    def _begin_qc_withdrawal(self, state, actor_id, intent_id, reaction_id, method, quantity):
        self._stage_ready(state, 'S11')
        reaction = self._reaction(state, reaction_id)
        material = state['inventory']['materials'][reaction['current_material_id']]
        if material['kind'] != 'product' or method not in state['definition']['manual_profile']['qc_plan']['roles'][reaction['role']]['methods']:
            raise TaskError('QC withdrawal requires the identified product and selected method')
        observed = ledger.quantity(quantity, units={'uL'})
        if observed['value'] is None:
            raise TaskError('An unknown QC dose cannot become a new instruction')
        changed = ledger.begin_effect(state, actor_id, intent_id, 'withdrawal',
            [{'material_id': material['id'], 'quantity': observed, 'consume_all': False}], [], 'manual_product_qc:' + method)
        if changed is False:
            return False
        state['manual']['actions'][intent_id] = {'operation': 'qc_withdrawal', 'reaction_id': reaction_id,
            'method': method, 'recorded_intent_at': copy.deepcopy(state['clock']['last_sample'])}
        self._after_material_change(state, True)

    def _record_external_stop(self, state, actor_id, reaction_id, actual_volume_ul, mixed, reason):
        if state['observation_context']['source_kind'] not in {'external_record', 'test_fixture'}:
            raise TaskError('Retrospective external action provenance required')
        reaction = self._reaction(state, reaction_id)
        if reaction['role'] == 'input':
            raise TaskError('Input has no CUT&RUN stop role')
        old = state['protective_operations'].get(reaction['vessel_id'])
        if old is not None and state['bookings'][old]['outcome'] not in {'intent', 'unknown'}:
            raise TaskError('An existing confirmed stop must not be debited again')
        if old is None:
            identity = 'EXTERNAL.' + state['observation_context']['observation_id']
            ledger.begin_protective_stop(state, actor_id, identity, reaction['vessel_id'],
                reaction['stop_material_id'], {'value': actual_volume_ul, 'unit': 'uL'},
                purpose='retrospective_external_stop_not_a_prior_electronic_intent')
            state['manual']['actions'][identity] = {'operation': 'stop', 'reaction_id': reaction_id,
                'retrospective': True, 'recorded_intent_at': copy.deepcopy(state['clock']['last_sample'])}
        else:
            identity = old
            state['manual']['actions'][identity]['retrospective_receipt'] = True
        self._confirm_dose(state, actor_id, identity, actual_volume_ul, mixed, reason)

    def _mark_unknown(self, state, actor_id, intent_id, reason):
        action = state['manual']['actions'].get(intent_id)
        if not action:
            raise TaskError('Unknown manual action')
        if action['operation'] == 'stop':
            changed = ledger.mark_protective_unknown(state, actor_id, intent_id, reason)
        else:
            changed = ledger.mark_unknown(state, actor_id, intent_id, reason)
        if changed is not False:
            state['recovery_required'], state['workspace_clear'] = 'unknown_material_effect', False
        return changed

    def _resolve_action(self, state, actor_id, intent_id, outcome, actual_inputs, actual_outputs, mixed, reason):
        action = state['manual']['actions'].get(intent_id)
        if action is None:
            raise TaskError('Unknown manual action')
        if outcome == 'unknown':
            return self._mark_unknown(state, actor_id, intent_id, reason)
        if outcome == 'performed':
            if action['operation'] in {'activation', 'stop'}:
                if not isinstance(actual_inputs, list) or len(actual_inputs) != 1 or actual_outputs != []:
                    raise TaskError('Explicit single actual dose required')
                expected = state['bookings'][intent_id]['request']['inputs'][0]['material_id']
                if actual_inputs[0]['material_id'] != expected or actual_inputs[0]['quantity']['unit'] != 'uL':
                    raise ObservationError('Dose source identity mismatch')
                return self._confirm_dose(state, actor_id, intent_id, actual_inputs[0]['quantity']['value'], mixed, reason)
            return self._confirm_material_action(state, actor_id, intent_id, actual_inputs, actual_outputs, reason)
        if outcome != 'not_performed':
            raise TaskError('Explicit performed, not_performed or unknown outcome required')
        if action['operation'] == 'stop':
            changed = ledger.resolve_protective_stop(state, actor_id, intent_id, outcome, None, reason)
        else:
            changed = ledger.not_performed(state, actor_id, intent_id, reason)
        if action['operation'] == 'activation':
            reaction = state['manual']['reactions'][action['reaction_id']]
            if reaction['stop'] is None:
                reaction['status'] = 'inactive'
            else:
                self._hold(state, 'activation_absent_after_stop', 'Protective stopping prevents an assumed nominal replay')
        return self._after_material_change(state, changed)

    def _resolve_clock_gap(self, state, actor_id, minimum_s, maximum_s, reason, evidence_ref):
        state['clock'] = process_clock.reconcile_gap(state['clock'], state['clock']['last_sample'],
            minimum_s, maximum_s, reason, evidence_ref)
        state['logical_time_s'] = state['clock']['lower_s']
        self._evaluate_reactions(state)

    def _check_clock(self, state, actor_id):
        self._evaluate_reactions(state)

    def _reconcile(self, state, actor_id, observations, workspace_clear, reason):
        text(reason, 'reconciliation record')
        if type(workspace_clear) is not bool:
            raise TaskError('Explicit work-area observation required')
        self._confirm_inventory(state, actor_id, observations)
        unresolved = any(item['outcome'] in {'intent', 'unknown'} for item in state['bookings'].values())
        quarantine = any(item['status'] == 'quarantined' for item in state['manual']['qc_artifacts'].values())
        state['recovery_required'] = ('unresolved_clock_gap' if state['clock']['gap_required'] else
            'unknown_material_effect' if unresolved else 'quarantined_qc' if quarantine else
            'manual_deviation' if any('resolution' not in item for item in state['manual']['holds']) else None)
        state['workspace_clear'] = workspace_clear
        self._evaluate_reactions(state)  # Neither task nor chemical deadlines are reset.

    def _resolve_deviation(self, state, actor_id, hold_code, reason, evidence_ref):
        text(evidence_ref, 'deviation assessment evidence reference')
        if (state['clock']['gap_required']
                or any(item['outcome'] in {'intent', 'unknown'} for item in state['bookings'].values())
                or any(item['status'] == 'quarantined' for item in state['manual']['qc_artifacts'].values())
                or any(item['status'] in {'possibly_active', 'active', 'stop_unconfirmed'}
                       for item in state['manual']['reactions'].values())):
            raise TaskError('Resolve actual effects, active reactions, clock gaps and QC quarantine before assessing a deviation')
        holds = [item for item in state['manual']['holds'] if item['code'] == hold_code and 'resolution' not in item]
        if not holds:
            raise TaskError('No unresolved deviation with this code')
        receipt = material_evidence.receipt(state, actor_id, reason, evidence_ref=evidence_ref)
        for hold in holds:
            hold['resolution'] = copy.deepcopy(receipt)
        # A separate full inventory/work-area reconciliation is still required.

    def _clarify_qc(self, state, actor_id, artifact_sha256, decision, reason):
        artifact = state['manual']['qc_artifacts'].get(artifact_sha256)
        if artifact is None or artifact['status'] != 'quarantined' or decision not in {'allow_remap', 'exclude'}:
            raise TaskError('Explicit clarification of a quarantined original required')
        artifact.setdefault('clarifications', []).append(material_evidence.receipt(state, actor_id, reason, decision=decision))
        artifact['status'] = 'unmapped' if decision == 'allow_remap' else 'excluded'
        for identity, binding in state['manual']['qc_bindings'].items():
            if binding['artifact_sha256'] == artifact_sha256:
                binding['invalidated'] = True
                state['manual']['qc_reviews'].pop(identity, None)
        # Original attempts and earlier assessments remain in the journal. No
        # previous mapping/review is automatically revalidated by clarification.

    def _attach_qc(self, state, artifact, file_name, origin='device_original'):
        if not isinstance(artifact, bytes) or not artifact or origin not in {'device_original', 'operator_transcription', 'external_record', 'test_fixture'}:
            raise TaskError('Original nonempty QC artifact bytes and explicit origin required')
        text(file_name, 'QC original file name')
        checksum = digest(artifact)
        if checksum in state['manual']['qc_artifacts']:
            return False
        state['manual']['qc_artifacts'][checksum] = {'file_name': file_name, 'byte_count': len(artifact),
            'origin': origin, 'status': 'unmapped', 'decoder': None,
            **material_evidence.provenance(state)}

    def _map_qc(self, state, actor_id, mapping_id, artifact_sha256, reaction_id, material_id, role,
                method, assay_id, calibration_ref, locator, result_status, value, unit, dilution,
                criteria_ref, reason):
        text(mapping_id, 'QC mapping identity')
        artifact = state['manual']['qc_artifacts'].get(artifact_sha256)
        if artifact is None:
            raise TaskError('Archive the original QC artifact first')
        if artifact['status'] in {'quarantined', 'excluded'}:
            raise TaskError('Explicit QC clarification is required before a new mapping')
        try:
            if role == 'ntc':
                if reaction_id is not None or material_id is not None or method != 'qpcr':
                    raise ObservationError('NTC is a separate non-sample QC role')
            else:
                reaction = self._reaction(state, reaction_id)
                material = state['inventory']['materials'].get(material_id)
                if role != reaction['role'] or material_id != reaction['current_material_id'] or material is None or material['kind'] != 'product':
                    raise ObservationError('QC must map to the actual reaction and purified product')
            if method not in {'fluorometry', 'qpcr'} or result_status not in {'quantified', 'below_loq', 'not_detected', 'invalid', 'unknown'}:
                raise ObservationError('Unsupported QC method or result status')
            text(assay_id, 'assay identity');text(calibration_ref, 'calibration/primer reference')
            text(locator, 'original row/well locator');text(criteria_ref, 'predeclared criteria reference')
            text(reason, 'manual mapping evidence')
            if role not in state['definition']['manual_profile']['qc_plan']['roles']:
                raise ObservationError('Unknown QC role')
            plan = state['definition']['manual_profile']['qc_plan']['roles'][role]
            if (method not in plan['methods']
                    or plan['evidence_ref'] is not None and criteria_ref != plan['evidence_ref']
                    or plan['assay_id'] is not None and assay_id != plan['assay_id']):
                raise ObservationError('QC method/assay/criteria do not match the predeclared role plan')
            if dilution is not None:
                from manual_workflow import positive
                positive(dilution, 'actual dilution factor')
            if result_status == 'quantified':
                from manual_workflow import positive
                try:
                    positive(value, 'quantified QC value', zero=method == 'qpcr')
                except TaskError as error:
                    raise ObservationError(str(error)) from error
            elif value is not None:
                raise ObservationError('Censored/unknown result is not a fabricated zero or concentration')
            if unit != {'fluorometry': 'ng/uL', 'qpcr': 'Cq'}[method]:
                raise ObservationError('QC result unit mismatch')
            request = {'artifact_sha256': artifact_sha256, 'reaction_id': reaction_id,
                'material_id': material_id, 'role': role, 'method': method, 'assay_id': assay_id,
                'calibration_ref': calibration_ref, 'locator': locator, 'result_status': result_status,
                'value': value, 'unit': unit, 'dilution': dilution, 'criteria_ref': criteria_ref, 'reason': reason,
                'actor_id': actor_id, **material_evidence.provenance(state)}
            for identity, previous in state['manual']['qc_bindings'].items():
                if identity != mapping_id and not previous.get('invalidated') and all(previous[key] == request[key] for key in ('artifact_sha256', 'locator', 'method', 'assay_id')):
                    raise ObservationError('The same original QC result cannot be reassigned to another mapping')
            old = state['manual']['qc_bindings'].get(mapping_id)
            if old is not None and old != request:
                raise ObservationError('Conflicting manual QC mapping identity')
            state['manual']['qc_bindings'][mapping_id] = request
            artifact['status'] = 'mapped'
        except (ObservationError, TaskError) as error:
            artifact['status'] = 'quarantined'
            artifact.setdefault('rejections', []).append({'mapping_id': mapping_id, 'reason': str(error),
                                                         **material_evidence.provenance(state)})
            self._hold(state, 'quarantined_qc', str(error))

    def _review_qc(self, state, actor_id, mapping_id, decision, reason):
        binding = state['manual']['qc_bindings'].get(mapping_id)
        if binding is None or binding.get('invalidated') or decision not in {'technically_accepted', 'rejected', 'inconclusive'}:
            raise TaskError('Explicit technical QC mapping review required')
        artifact = state['manual']['qc_artifacts'][binding['artifact_sha256']]
        if artifact['status'] in {'quarantined', 'excluded'}:
            raise TaskError('Quarantined original evidence needs explicit clarification')
        state['manual']['qc_reviews'][mapping_id] = material_evidence.receipt(state, actor_id, reason, decision=decision)

    def _review_biology(self, state, actor_id, mapping_ids, decision, criteria_ref, reason):
        if decision not in {'accepted', 'rejected', 'inconclusive'} or not isinstance(mapping_ids, list) or not mapping_ids:
            raise TaskError('Explicit independent biological assessment required')
        if any(identity not in state['manual']['qc_reviews'] for identity in mapping_ids):
            raise TaskError('Technical QC review must precede biological assessment')
        if decision == 'accepted' and not state['definition']['stage_readiness'].get('S11', False):
            raise TaskError('Open assay/criteria bindings cannot establish biological acceptance')
        for identity in mapping_ids:
            binding = state['manual']['qc_bindings'][identity]
            if (binding.get('invalidated')
                    or state['manual']['qc_artifacts'][binding['artifact_sha256']]['status'] in {'quarantined', 'excluded'}
                    or binding['criteria_ref'] != criteria_ref or state['manual']['qc_reviews'][identity]['decision'] != 'technically_accepted'):
                raise TaskError('Biological review requires matching predeclared criteria and accepted technical records')
        state['manual']['biology_reviews'][state['observation_context']['observation_id']] = material_evidence.receipt(
            state, actor_id, reason, decision=decision, criteria_ref=text(criteria_ref, 'criteria reference'),
            mapping_ids=copy.deepcopy(mapping_ids), technical_reviews_sha256={identity:
                digest(encoded(state['manual']['qc_reviews'][identity]).encode()) for identity in mapping_ids})

    def _set_disposition(self, state, actor_id, material_id, disposition, reason):
        for reaction in state['manual']['reactions'].values():
            if reaction['current_material_id'] == material_id:
                if reaction['status'] in {'possibly_active', 'active', 'stop_unconfirmed'}:
                    raise TaskError('Active/uncertain reaction needs explicit stop/abnormal reconciliation before disposition')
                if reaction['status'] == 'abnormal_unconfirmed_stop' and disposition != 'quarantined':
                    raise TaskError('Abnormal unconfirmed stopping requires explicit quarantine')
        return super()._set_disposition(state, actor_id, material_id, disposition, reason)

    def _abnormal_termination(self, state, actor_id, reaction_id, reason):
        if state['status'] != 'cancelling':
            raise TaskError('Explicit cancellation required before abnormal handover')
        reaction = self._reaction(state, reaction_id)
        reaction['abnormal_termination'] = material_evidence.receipt(state, actor_id, reason,
            chemical_stop_confirmed=reaction['status'] == 'stopped')
        if reaction['status'] != 'stopped':
            reaction['status'] = 'abnormal_unconfirmed_stop'

    def _restored(self, state):
        if any(item['status'] in {'possibly_active', 'active', 'stop_unconfirmed'} for item in state['manual']['reactions'].values()):
            raise TaskError('Manual capture cannot release an unconfirmed active reaction')
        super()._restored(state)

    def _close_capture(self, state, actor_id, workspace_clear, reason):
        text(reason, 'capture handover reason')
        if workspace_clear is not True:
            raise ObservationError('Explicit capture handover observation required')
        if state['recovery_required'] or state['clock']['gap_required']:
            raise TaskError('Resolve deviations and reconcile before normal capture handover')
        self._restored(state)
        self._finish_lifecycle(state, 'completed')

    def act(self, command, actor_id, artifact=None, *, observation, **data):
        alias = {'attach_qc': 'import_results'}
        if command not in set(self.STEPS) | {'reconcile', 'cancel', 'finish_cancel'}:
            raise TaskError('Generic/synthetic commands cannot bypass the manual capture contract')
        state = self.state
        if self.session is None or state['session'] != self.session or state['status'] in {'completed', 'cancelled'}:
            raise TaskError('Stale or terminal manual session')
        self._authorize_actor(state, command, actor_id)
        keys(observation, 'observation_id source_kind observed_at source_ref artifact_sha256', 'manual observation envelope')
        envelope = copy.deepcopy(observation)
        if envelope['observed_at'] is not None:
            keys(envelope['observed_at'], 'earliest_utc latest_utc', 'observed occurrence interval')
            start = utc(envelope['observed_at']['earliest_utc'])
            end = envelope['observed_at']['latest_utc']
            if end is not None and utc(end) < start:
                raise TaskError('Observed occurrence interval is reversed')
        text(envelope['source_ref'], 'observation source reference')
        if artifact is not None:
            if not isinstance(artifact, bytes):
                raise TaskError('Original artifact bytes required')
            if envelope['artifact_sha256'] not in (None, digest(artifact)):
                raise TaskError('Observation original-artifact checksum mismatch')
            envelope['artifact_sha256'] = digest(artifact)
        elif envelope['artifact_sha256'] is not None:
            self.journal.artifact(envelope['artifact_sha256'])
        proposal = copy.deepcopy(state);proposal['observation_context'] = envelope
        material_evidence.provenance(proposal)
        if state['definition']['clock_source_kind'] == 'test_clock' and envelope['source_kind'] != 'test_fixture':
            raise TaskError('Test-clock records must explicitly identify test-fixture observations')
        fingerprint = digest(encoded({'command': command, 'actor_id': actor_id, 'data': data,
                                      'observation': envelope}).encode())
        old = state['manual']['observations'].get(envelope['observation_id'])
        if old is not None:
            if old != fingerprint:
                raise TaskError('Observation identity reused with different content')
            return state
        self._observation = envelope
        self._fingerprint = fingerprint
        try:
            # Shared dispatch retains CAS, error journaling and artifact atomicity.
            return ManualWorkflow.act(self, alias.get(command, command), actor_id, artifact=artifact,
                                      **data)
        finally:
            self._observation = None
            self._fingerprint = None

    def _import_results(self, state, artifact, file_name, origin='device_original', _manual_observation_hash=None):
        return self._attach_qc(state, artifact, file_name, origin)

    def _report(self, state, trace):
        report = super()._report(state, trace)
        last_clock = copy.deepcopy(state['clock'])
        current_clock = (last_clock if state['status'] in {'completed', 'cancelled'} else
                         process_clock.refresh(last_clock, process_clock.validate_sample(self.clock_provider.sample())))
        manual = copy.deepcopy(state['manual'])
        for assessment in manual['biology_reviews'].values():
            assessment['current_evidence_valid'] = all(
                identity in manual['qc_reviews']
                and not manual['qc_bindings'][identity].get('invalidated')
                and manual['qc_artifacts'][manual['qc_bindings'][identity]['artifact_sha256']]['status'] == 'mapped'
                and digest(encoded(manual['qc_reviews'][identity]).encode()) == checksum
                for identity, checksum in assessment['technical_reviews_sha256'].items())
        for reaction in manual['reactions'].values():
            activation = reaction['activation']
            if activation is None:
                reaction['possible_exposure_s'] = None
            else:
                end = reaction['stop']['recorded_clock'] if reaction['status'] == 'stopped' and reaction['stop'] else current_clock
                lower, upper = activation.get('start_lower_s'), activation.get('contact_upper_s')
                reaction['possible_exposure_s'] = {
                    # A stop capture is an upper endpoint, not the time of the
                    # physical stop. In particular retrospective records may
                    # describe a much earlier occurrence. Do not turn latency
                    # into a fabricated minimum exposure.
                    'min_s': 0 if upper is None or reaction['status'] == 'stopped' else max(0, end['lower_s'] - upper),
                    'max_s': None if lower is None or end['upper_s'] is None else max(0, end['upper_s'] - lower)}
        report.update(format=self.REPORT_FORMAT, mode='manual_observation',
            passed=False, reference_success=False, execution_ready=False,
            capture_completed=state['status'] == 'completed', manual=manual,
            clock=last_clock, current_clock_estimate=current_clock, current_clock_estimate_is_uncommitted=True,
            open_requirements=copy.deepcopy(state['definition']['open_requirements']),
            stage_readiness=copy.deepcopy(state['definition']['stage_readiness']),
            clock_source_kind=state['definition']['clock_source_kind'],
            biochemical_protocol_executed=False, authenticated_actor=False, vendor_qc_decoder_executed=False,
            limitations=['Manual evidence capture kernel, not a qualified complete SOP executor.',
                         'Opaque original files with explicit human mapping; no native vendor decoder.',
                         'Open laboratory bindings remain open; capture completion is not reference success.',
                         'System clock observations alone do not qualify clock uncertainty or suspend continuity.'])
        return report
