"""Manual SOP stage order and declared time/temperature evidence on material /3.

The graph is the local SOP draft's stage sequence, not a vendor recipe decoder.
No equipment is operated and no laboratory qualification or outcome is inferred.
"""
import copy

import cutrun_sop_evidence as evidence
import material_evidence
import material_ledger as ledger
from cutrun_manual_workflow import CutRunManualWorkflow
from manual_tasks import TaskError, digest, encoded
from manual_workflow import text


class CutRunManualSopWorkflow(CutRunManualWorkflow):
    ENGINE = 'cutrun_manual_sop/1'
    REPORT_FORMAT = 'solidcraftbot.cutrun-manual-sop-report/1'
    MATERIAL_STAGES = CutRunManualWorkflow.MATERIAL_STAGES | {'S08'}
    STEPS = (*CutRunManualWorkflow.STEPS, 'begin_stage', 'complete_stage',
             'record_phase_time', 'record_phase_temperature', 'attach_sop_evidence')
    RECOVERY_COMMANDS = CutRunManualWorkflow.RECOVERY_COMMANDS | {
        'record_phase_time', 'record_phase_temperature', 'attach_sop_evidence'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    @classmethod
    def _load_definition(cls, source, **kwargs):
        from cutrun_manual_sop_sources import load
        return load(source, **kwargs)

    @classmethod
    def _extra_state(cls, definition, reactions):
        if {item['role'] for item in reactions.values()} != {'h3k4me3', 'igg', 'input'}:
            raise TaskError('The complete SOP contract needs H3K4me3, IgG and a separate Input')
        return {'sop': {'engine': cls.ENGINE, 'stages': {}, 'by_key': {}, 'evidence': {}, 'artifacts': {}}}

    @classmethod
    def _validate_format(cls, state):
        super()._validate_format(state)
        if state.get('sop', {}).get('engine') != cls.ENGINE:
            raise TaskError('Matching SOP stage engine required; no capture-only run migration')

    @staticmethod
    def _key(stage_id, reaction_id):
        return encoded([stage_id, reaction_id])

    def _find_stage(self, state, stage_id, reaction_id):
        identity = state['sop']['by_key'].get(self._key(stage_id, reaction_id))
        return None if identity is None else state['sop']['stages'][identity]

    @staticmethod
    def _stage(state, stage_run_id):
        text(stage_run_id, 'SOP stage run identity')
        stage = state['sop']['stages'].get(stage_run_id)
        if stage is None:
            raise TaskError('Unknown SOP stage run')
        return stage

    def _require_stage(self, state, stage_id, reaction_id=None):
        if stage_id in state['definition']['sop_protocol']['global_stages']:
            reaction_id = None
        stage = self._find_stage(state, stage_id, reaction_id)
        if stage is None or stage['status'] != 'open':
            raise TaskError('An explicitly open matching SOP stage is required: ' + stage_id)
        return stage

    def _stage_ready(self, state, stage_id):
        super()._stage_ready(state, stage_id)
        if not any(item['stage_id'] == stage_id and item['status'] == 'open'
                   for item in state['sop']['stages'].values()):
            raise TaskError('Begin the SOP stage before issuing an ordinary action')

    @staticmethod
    def _authorize_actor(state, command, actor_id):
        observed = command in {'record_phase_time', 'record_phase_temperature', 'attach_sop_evidence'}
        CutRunManualWorkflow._authorize_actor(state, 'record_observation' if observed else command, actor_id)

    def _completed(self, state, stage_id, reaction_id=None):
        stage = self._find_stage(state, stage_id, reaction_id)
        if not (stage and stage['status'] == 'completed' and self._stage_assessment(state, stage)['conformant']):
            return False
        if stage_id == 'S01':return True
        if stage_id == 'S11':
            return all(self._completed(state, 'S10', identity) for identity in state['manual']['reactions'])
        if stage_id == 'S12':return self._completed(state, 'S11')
        role = state['manual']['reactions'][reaction_id]['role']
        path = state['definition']['sop_protocol']['branch_sequences'][role]
        index = path.index(stage_id)
        return (self._completed(state, 'S01') if index == 0
                else self._completed(state, path[index - 1], reaction_id))

    def _begin_stage(self, state, actor_id, stage_id, reaction_id, stage_run_id):
        text(stage_run_id, 'SOP stage run identity')
        protocol = state['definition']['sop_protocol']
        if stage_id not in protocol['stages']:
            raise TaskError('Unknown local SOP stage')
        node = protocol['stages'][stage_id]
        if node['scope'] == 'run':
            if reaction_id is not None:
                raise TaskError('A global SOP stage has no reaction identity')
        else:
            reaction = self._reaction(state, reaction_id)
            if reaction['role'] not in node['roles']:
                raise TaskError('The stage does not apply to this reaction role')
        old = self._find_stage(state, stage_id, reaction_id)
        if old is not None:
            if old['id'] == stage_run_id:
                return False
            raise TaskError('A SOP stage cannot restart under a new identity')
        if stage_run_id in state['sop']['stages']:
            raise TaskError('SOP stage identity is already used')
        CutRunManualWorkflow._stage_ready(self, state, stage_id)
        if any(item['status'] in {'possibly_active', 'active', 'stop_unconfirmed'}
               for item in state['manual']['reactions'].values()):
            raise TaskError('Protect and reconcile the active reaction before starting another stage')
        if stage_id != 'S01' and not self._completed(state, 'S01'):
            raise TaskError('Complete the run opening before a material stage')
        if stage_id == 'S11':
            if not all(self._completed(state, 'S10', identity) for identity in state['manual']['reactions']):
                raise TaskError('All three identified products must reach purification before QC')
        elif stage_id == 'S12':
            if not self._completed(state, 'S11'):
                raise TaskError('Complete current QC and its separate assessment before handover')
        elif node['scope'] == 'reaction':
            path = protocol['branch_sequences'][state['manual']['reactions'][reaction_id]['role']]
            previous = path[:path.index(stage_id)]
            if not all(self._completed(state, item, reaction_id) for item in previous):
                raise TaskError('Earlier stages on this reaction path remain incomplete')
        material_id = vessel_id = None
        if reaction_id is not None:
            material_id = state['manual']['reactions'][reaction_id]['current_material_id']
            vessel_id = state['inventory']['materials'][material_id]['vessel_id']
        state['sop']['stages'][stage_run_id] = {
            'id': stage_run_id, 'stage_id': stage_id, 'reaction_id': reaction_id,
            'material_id': material_id, 'vessel_id': vessel_id, 'status': 'open',
            'started_at': copy.deepcopy(state['clock']['last_sample']),
            'phases': {name: {'times': [], 'temperatures': []} for name in node['phases']},
            'completion': None, 'begin_receipt': material_evidence.receipt(state, actor_id, 'SOP stage intent')}
        state['sop']['by_key'][self._key(stage_id, reaction_id)] = stage_run_id

    @staticmethod
    def _identity(stage, phase_id):
        return {'stage_run_id': stage['id'], 'phase_id': phase_id,
            'reaction_id': stage['reaction_id'], 'material_id': stage['material_id'], 'vessel_id': stage['vessel_id']}

    def _attach_sop_evidence(self, state, actor_id, file_name, origin):
        text(file_name, 'SOP original file name')
        if origin not in {'device_original', 'operator_transcription', 'external_record', 'test_fixture'}:
            raise TaskError('Explicit SOP original provenance required')
        checksum = state['observation_context']['artifact_sha256']
        if checksum is None:
            raise TaskError('Original SOP evidence bytes or an already archived reference required')
        if checksum in state['sop']['artifacts']:return False
        state['sop']['artifacts'][checksum] = {'file_name': file_name, 'origin': origin,
            'receipt': material_evidence.receipt(state, actor_id, 'Original manual SOP evidence attachment')}

    def _owned_original(self, state, checksum):
        if (checksum not in state['definition']['initial_artifact_sha256']
                and checksum not in state['sop']['artifacts']
                and checksum not in state['manual']['qc_artifacts']):
            raise TaskError('Attach this original to the current run before using its evidence')
        return self.journal.artifact(checksum)

    def _record_phase(self, state, actor_id, stage_run_id, phase_id, record, kind):
        stage = self._stage(state, stage_run_id)
        if phase_id not in stage['phases']:
            raise TaskError('The phase does not belong to this SOP stage')
        qualifiers = state['definition']['sop_profile']['qualifications']
        validator = evidence.validate_time if kind == 'times' else evidence.validate_temperature
        value = validator(record, self._identity(stage, phase_id), qualifiers)
        if value['source_kind'] != state['observation_context']['source_kind']:
            raise TaskError('Phase evidence and its observation provenance must agree')
        self._owned_original(state, value['artifact_sha256'])
        old = state['sop']['evidence'].get(value['evidence_id'])
        if old is not None:
            if old['record'] == value:
                return False
            raise TaskError('SOP evidence identity reused with different content')
        if kind == 'times' and value['time_basis_id'] == state['clock']['last_sample']['clock_id']:
            captured = state['clock']['last_sample']['monotonic_ns'] / 1_000_000_000
            uncertainty = state['clock']['last_sample']['uncertainty_s']
            start = stage['started_at']['monotonic_ns'] / 1_000_000_000
            if stage['started_at']['clock_id'] == value['time_basis_id']:
                if value['start_earliest_s'] is not None and value['start_earliest_s'] < start:
                    raise TaskError('A normal stage phase cannot predate its recorded stage intent')
            if value['end_latest_s'] is not None and uncertainty is not None and value['end_latest_s'] > captured + uncertainty:
                raise TaskError('A phase completion cannot claim a future observed occurrence')
        stage['phases'][phase_id][kind].append(value)
        state['sop']['evidence'][value['evidence_id']] = {'record': copy.deepcopy(value),
            'capture': copy.deepcopy(state['clock']['last_sample']),
            'receipt': material_evidence.receipt(state, actor_id, 'Manual SOP phase observation')}
        result = self._phase_assessment(state, stage, phase_id)
        contradictory = [item for item in result['issues'] if any(name in item for name in
            ('out_of_range', 'duration_above', 'duration_below', 'conflicting_time',
             'occurrence_order', 'dose_duration_conflict'))]
        if contradictory or stage['status'] == 'completed' and not result['conformant']:
            self._hold(state, 'sop_phase_deviation', stage_run_id + ':' + phase_id + ':' + ','.join(result['issues']))

    def _record_phase_time(self, state, actor_id, stage_run_id, phase_id, record):
        return self._record_phase(state, actor_id, stage_run_id, phase_id, record, 'times')

    def _record_phase_temperature(self, state, actor_id, stage_run_id, phase_id, record):
        return self._record_phase(state, actor_id, stage_run_id, phase_id, record, 'temperatures')

    def _phase_assessment(self, state, stage, phase_id):
        phase = stage['phases'][phase_id]
        if not phase['times']:
            return {'conformant': False, 'complete': False, 'issues': ['time_evidence_missing']}
        bounds = ('start_earliest_s', 'start_latest_s', 'end_earliest_s', 'end_latest_s')
        complete = [item for item in phase['times'] if all(item[name] is not None for name in bounds)]
        selected = complete[-1] if complete else phase['times'][-1]
        result = evidence.evaluate_phase(selected, phase['temperatures'],
            state['definition']['sop_profile']['phase_requirements'][phase_id],
            state['definition']['sop_profile']['qualifications'])
        for previous in phase['times']:
            if previous is selected:
                continue
            conflict = previous['time_basis_id'] != selected['time_basis_id']
            for lower, upper in [('start_earliest_s', 'start_latest_s'), ('end_earliest_s', 'end_latest_s')]:
                conflict |= bool(previous[lower] is not None and selected[lower] is not None and selected[lower] < previous[lower])
                conflict |= bool(previous[upper] is not None and selected[upper] is not None and selected[upper] > previous[upper])
            if conflict:
                result['issues'].append('conflicting_time_evidence:' + previous['evidence_id'])
        result['conformant'] = result['complete'] = not result['issues']
        result['selected_time_evidence_id'] = selected['evidence_id']
        if stage['stage_id'] == 'S07':
            reaction = state['manual']['reactions'][stage['reaction_id']]
            activation, stop = reaction.get('activation'), reaction.get('stop')
            if activation and stop:
                activation_action = state['manual']['actions'][activation['intent_id']]
                stop_action = state['manual']['actions'][stop['intent_id']]
                maximum = (None if stop['recorded_clock']['upper_s'] is None or activation['start_lower_s'] is None
                           else max(0, stop['recorded_clock']['upper_s'] - activation['start_lower_s']))
                minimum = None
                if not any(action.get('retrospective') or action.get('retrospective_receipt')
                           for action in (activation_action, stop_action)):
                    stop_intent = stop_action.get('intent_process_bounds', {})
                    minimum = (None if stop_intent.get('lower_s') is None or activation.get('contact_upper_s') is None
                               else max(0, stop_intent['lower_s'] - activation['contact_upper_s']))
                declared = result['duration_bounds']
                if (maximum is not None and declared['min_s'] is not None and declared['min_s'] > maximum
                        or minimum is not None and declared['max_s'] is not None and declared['max_s'] < minimum):
                    result['issues'].append('dose_duration_conflict')
            for operation, point in [('activation', 'start'), ('stop', 'end')]:
                effect = reaction.get(operation)
                if effect is None:continue
                action = state['manual']['actions'][effect['intent_id']]
                if action.get('retrospective') or action.get('retrospective_receipt'):continue
                beginning, ending = action.get('recorded_intent_at'), action.get('confirmed_at_clock')
                if beginning and ending and beginning['clock_id'] == ending['clock_id'] == selected['time_basis_id']:
                    earliest, latest = selected[point + '_earliest_s'], selected[point + '_latest_s']
                    lower = beginning['monotonic_ns'] / 1_000_000_000
                    upper = ending['monotonic_ns'] / 1_000_000_000
                    if (earliest is not None and earliest > upper or latest is not None and latest < lower):
                        result['issues'].append(operation + '_occurrence_not_linked_to_dose')
        result['conformant'] = result['complete'] = not result['issues']
        return result

    def _stage_assessment(self, state, stage):
        phases = {name: self._phase_assessment(state, stage, name) for name in stage['phases']}
        issues = [name + ':' + issue for name, result in phases.items() for issue in result['issues']]
        previous = None
        for phase_id in stage['phases']:
            phase = stage['phases'][phase_id]
            result = phases[phase_id]
            selected = next((item for item in phase['times']
                if item['evidence_id'] == result.get('selected_time_evidence_id')), None)
            if selected and previous:
                if (selected['time_basis_id'] != previous['time_basis_id']
                        or selected['start_earliest_s'] is None or previous['end_latest_s'] is None
                        or selected['start_earliest_s'] < previous['end_latest_s']):
                    issues.append('phase_order_not_established:' + phase_id)
            if selected:previous = selected
        if stage['reaction_id'] is not None and stage['phases']:
            role = state['manual']['reactions'][stage['reaction_id']]['role']
            path = state['definition']['sop_protocol']['branch_sequences'][role]
            first_phase = next(iter(stage['phases']))
            current_id = phases[first_phase].get('selected_time_evidence_id')
            current = next((item for item in stage['phases'][first_phase]['times'] if item['evidence_id'] == current_id), None)
            for previous_id in reversed(path[:path.index(stage['stage_id'])]):
                earlier = self._find_stage(state, previous_id, stage['reaction_id'])
                if earlier is None or not earlier['phases']:continue
                last_phase = next(reversed(earlier['phases']))
                assessment = self._phase_assessment(state, earlier, last_phase)
                selected_id = assessment.get('selected_time_evidence_id')
                previous = next((item for item in earlier['phases'][last_phase]['times']
                                 if item['evidence_id'] == selected_id), None)
                if current and previous and (current['time_basis_id'] != previous['time_basis_id']
                        or current['start_earliest_s'] is None or previous['end_latest_s'] is None
                        or current['start_earliest_s'] < previous['end_latest_s']):
                    issues.append('preceding_phase_order_not_established')
                break
        if stage['stage_id'] == 'S11' and stage['completion'] is not None:
            if stage['completion'].get('qc_snapshot_sha256') != self._qc_snapshot(state):
                issues.append('qc_evidence_changed_after_completion')
        if stage['stage_id'] == 'S12' and stage['completion'] is not None:
            inventory = self._inventory_digest(state)
            confirmation = state['inventory_confirmation']
            if (stage['completion'].get('inventory_snapshot_sha256') != inventory
                    or not confirmation or confirmation['inventory_sha256'] != inventory
                    or any(item['outcome'] in {'intent', 'unknown'} for item in state['bookings'].values())
                    or any(item['disposition'] is None or not item['disposition_confirmation']
                           for item in state['inventory']['materials'].values())):
                issues.append('handover_inventory_changed_after_completion')
        return {'conformant': not issues, 'phases': phases, 'issues': issues}

    def _before_transition(self, state):
        super()._before_transition(state)
        self._check_completed(state)

    def _check_completed(self, state):
        for stage in state['sop']['stages'].values():
            if stage['status'] == 'completed':
                result = self._stage_assessment(state, stage)
                if not result['conformant']:
                    self._hold(state, 'sop_completed_stage_invalidated', stage['id'] + ':' + ','.join(result['issues']))

    def _reconcile(self, state, actor_id, observations, workspace_clear, reason):
        super()._reconcile(state, actor_id, observations, workspace_clear, reason)
        self._check_completed(state)

    def _tag(self, state, intent_id, stage_id, reaction_id):
        action = state['manual']['actions'][intent_id]
        stage = self._find_stage(state, stage_id, None if stage_id == 'S11' else reaction_id)
        action['stage_id'] = stage_id
        action['stage_run_id'] = None if stage is None else stage['id']

    def _begin_material_action(self, state, actor_id, intent_id, reaction_id, stage_id, **kwargs):
        self._require_stage(state, stage_id, reaction_id)
        changed = super()._begin_material_action(state, actor_id, intent_id, reaction_id, stage_id, **kwargs)
        if changed is not False:self._tag(state, intent_id, stage_id, reaction_id)
        return changed

    def _begin_activation(self, state, actor_id, intent_id, reaction_id, stop_access, mixing_available):
        self._require_stage(state, 'S07', reaction_id)
        binding = state['definition']['sop_profile']['phase_requirements']['S07.digestion']
        target = self._parameter(state, 'activation_duration_s')
        if target is None or not binding['duration_min_s'] <= target <= binding['duration_max_s']:
            raise TaskError('Activation duration and prospective digestion bounds must agree')
        temperature = self._parameter(state, 'activation_temperature_deg_c')
        if temperature is None or not binding['temperature_min_deg_c'] <= temperature <= binding['temperature_max_deg_c']:
            raise TaskError('Activation temperature target and prospective digestion bounds must agree')
        changed = super()._begin_activation(state, actor_id, intent_id, reaction_id, stop_access, mixing_available)
        if changed is not False:self._tag(state, intent_id, 'S07', reaction_id)
        return changed

    def _confirm_dose(self, state, actor_id, intent_id, actual_volume_ul, mixed, reason):
        changed = super()._confirm_dose(state, actor_id, intent_id, actual_volume_ul, mixed, reason)
        if changed is not False:
            state['manual']['actions'][intent_id]['confirmed_at_clock'] = copy.deepcopy(state['clock']['last_sample'])
        return changed

    def _begin_stop(self, state, actor_id, intent_id, reaction_id, stop_access, mixing_available):
        existed = intent_id in state['manual']['actions']
        changed = super()._begin_stop(state, actor_id, intent_id, reaction_id, stop_access, mixing_available)
        if not existed and intent_id in state['manual']['actions'] and changed is not False:
            self._tag(state, intent_id, 'S08', reaction_id)
            state['manual']['actions'][intent_id]['intent_process_bounds'] = {
                name: state['clock'][name] for name in ('lower_s', 'upper_s')}
        return changed

    def _begin_qc_withdrawal(self, state, actor_id, intent_id, reaction_id, method, quantity):
        self._require_stage(state, 'S11')
        changed = super()._begin_qc_withdrawal(state, actor_id, intent_id, reaction_id, method, quantity)
        if changed is not False:self._tag(state, intent_id, 'S11', reaction_id)
        return changed

    def _canonical_actions(self, state, stage, action_ids):
        if not isinstance(action_ids, list) or len(action_ids) != len(set(action_ids)):
            raise TaskError('Unique canonical material action references required')
        records = []
        for identity in action_ids:
            action = state['manual']['actions'].get(identity)
            booking = state['bookings'].get(identity)
            if action is None or booking is None or booking['outcome'] != 'performed':
                raise TaskError('Every supplied action must be a confirmed canonical material effect')
            if action['operation'] == 'stop' and stage['stage_id'] in {'S07', 'S08'}:
                if action['reaction_id'] != stage['reaction_id']:
                    raise TaskError('Stop action belongs to another reaction')
            elif action.get('stage_run_id') != stage['id']:
                raise TaskError('Material action belongs to a different stage run')
            records.append((identity, action, booking))
        if stage['stage_id'] in self.MATERIAL_STAGES and not any(action['operation'] == 'material' for _, action, _ in records):
            raise TaskError('Observed material handling needs a linked canonical material receipt')
        return records

    @staticmethod
    def _qc_snapshot(state):
        manual = state['manual']
        return digest(encoded({name: manual[name] for name in
            ('qc_artifacts', 'qc_bindings', 'qc_reviews', 'biology_reviews')}).encode())

    def _qc_complete(self, state, records):
        manual = state['manual']
        accepted = set()
        for identity, binding in manual['qc_bindings'].items():
            review = manual['qc_reviews'].get(identity)
            artifact = manual['qc_artifacts'][binding['artifact_sha256']]
            if (not binding.get('invalidated') and artifact['status'] == 'mapped' and review
                    and review['decision'] == 'technically_accepted'):
                accepted.add(identity)
        plan = state['definition']['manual_profile']['qc_plan']['roles']
        for role, requirement in plan.items():
            for method in requirement['methods']:
                matching = [identity for identity in accepted if manual['qc_bindings'][identity]['role'] == role
                            and manual['qc_bindings'][identity]['method'] == method]
                if not matching:
                    raise TaskError('Current technical QC evidence missing for ' + role + '/' + method)
                if role != 'ntc':
                    reaction = next(identity for identity, value in manual['reactions'].items() if value['role'] == role)
                    if not any(action['operation'] == 'qc_withdrawal' and action['reaction_id'] == reaction
                               and action['method'] == method for _, action, _ in records):
                        raise TaskError('Each product assay needs its actual canonical QC withdrawal')
        assessed = set()
        for assessment in manual['biology_reviews'].values():
            if all(identity in accepted and digest(encoded(manual['qc_reviews'][identity]).encode()) == checksum
                   for identity, checksum in assessment['technical_reviews_sha256'].items()):
                assessed.update(assessment['mapping_ids'])
        for role, requirement in plan.items():
            for method in requirement['methods']:
                if not any(identity in assessed and manual['qc_bindings'][identity]['role'] == role
                           and manual['qc_bindings'][identity]['method'] == method for identity in accepted):
                    raise TaskError('A separate current biological assessment is required for every QC role/method')

    def _complete_stage(self, state, actor_id, stage_run_id, receipts, action_ids, reason):
        stage = self._stage(state, stage_run_id)
        if stage['status'] != 'open':
            raise TaskError('Only an open SOP stage can receive its first completion')
        CutRunManualWorkflow._stage_ready(self, state, stage['stage_id'])
        node = state['definition']['sop_protocol']['stages'][stage['stage_id']]
        if not isinstance(receipts, dict) or set(receipts) != set(node['completion_evidence']):
            raise TaskError('Complete typed SOP completion evidence is required')
        for reference in receipts.values():
            text(reference, 'registered stage observation original reference')
            record = state['definition']['evidence_records'].get(reference)
            self._owned_original(state, record['sha256'] if record is not None else reference)
        records = self._canonical_actions(state, stage, action_ids)
        assessment = self._stage_assessment(state, stage)
        if not assessment['conformant']:
            raise TaskError('SOP time/temperature conformance remains unresolved: ' + ','.join(assessment['issues']))
        if stage['stage_id'] == 'S07':
            reaction = state['manual']['reactions'][stage['reaction_id']]
            if reaction['status'] != 'stopped' or reaction['activation'] is None:
                raise TaskError('Digestion cannot finish while the physical reaction remains possibly active')
            activation = state['bookings'][reaction['activation']['intent_id']]
            if activation['outcome'] != 'performed' or not state['manual']['actions'][activation['id']].get('mixing_confirmed'):
                raise TaskError('Observed activation dose and mixing receipt required')
            if activation['id'] not in action_ids:
                raise TaskError('Link the actual activation receipt to digestion completion')
        elif stage['stage_id'] in {'S08', 'S10'}:
            reaction = state['manual']['reactions'][stage['reaction_id']]
            material = state['inventory']['materials'][reaction['current_material_id']]
            kind = 'product' if stage['stage_id'] == 'S10' else 'intermediate'
            if material['kind'] != kind or not any(action.get('retained_material_id') == material['id'] for _, action, _ in records):
                raise TaskError('Canonical retained fraction identity is missing')
            if stage['stage_id'] == 'S08':
                if reaction['status'] != 'stopped' or reaction['stop'] is None or reaction['stop']['intent_id'] not in action_ids:
                    raise TaskError('Confirmed chemical stop and its canonical receipt are required')
        elif stage['stage_id'] == 'S11':
            self._qc_complete(state, records)
        elif stage['stage_id'] == 'S12':
            self._restored(state)
        stage['completion'] = {'receipts': copy.deepcopy(receipts), 'action_ids': copy.deepcopy(action_ids),
            'assessment': assessment, 'captured_at': copy.deepcopy(state['clock']['last_sample']),
            'receipt': material_evidence.receipt(state, actor_id, reason)}
        if stage['stage_id'] == 'S11':stage['completion']['qc_snapshot_sha256'] = self._qc_snapshot(state)
        if stage['stage_id'] == 'S12':stage['completion']['inventory_snapshot_sha256'] = self._inventory_digest(state)
        stage['status'] = 'completed'

    def _audit_artifacts(self, trace):
        super()._audit_artifacts(trace)
        for checksum in trace[-1]['state']['sop']['artifacts']:
            self.journal.artifact(checksum)
        for item in trace[-1]['state']['sop']['evidence'].values():
            self.journal.artifact(item['record']['artifact_sha256'])

    def _close_capture(self, state, actor_id, workspace_clear, reason):
        self._check_completed(state)
        if not self._completed(state, 'S12'):
            raise TaskError('Complete the entire SOP graph and current handover before normal closure')
        return super()._close_capture(state, actor_id, workspace_clear, reason)

    def _report(self, state, trace):
        report = super()._report(state, trace)
        stages = copy.deepcopy(state['sop']['stages'])
        for identity, stage in stages.items():
            stage['current_assessment'] = self._stage_assessment(state, state['sop']['stages'][identity])
        report['sop'] = {'engine': self.ENGINE, 'stages': stages,
            'sequence_complete': self._completed(state, 'S12'),
            'stage_order_enforced': True, 'vendor_recipe_completeness_checked': False}
        report['limitations'] = [
            'Local SOP stage order and declared phase evidence are checked; no equipment or biochemical execution is proved.',
            'The detailed vendor recipes, all wash substeps and all recipe component consumptions are not decoded.',
            'Prospective clock/probe records are declarations with preserved originals, not independent qualification or authentication.',
            'Open laboratory parameters remain open; capture completion is not reference success.']
        return report
