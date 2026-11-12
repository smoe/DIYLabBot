"""Manual wash and reagent effects on the existing SOP graph and material ledger.

Recipe cursors contain no quantities. All material amounts and ancestry remain
canonical ledger bookings; physical mixing and separation have explicit receipts.
"""
import copy

import cutrun_recipe_bindings as bindings
import material_evidence
import material_ledger as ledger
from cutrun_manual_sop_workflow import CutRunManualSopWorkflow
from cutrun_manual_workflow import CutRunManualWorkflow
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ObservationError, text


class CutRunManualRecipeWorkflow(CutRunManualSopWorkflow):
    ENGINE = 'cutrun_manual_recipe/1'
    REPORT_FORMAT = 'solidcraftbot.cutrun-manual-recipe-report/1'
    STEPS = (*CutRunManualSopWorkflow.STEPS, 'begin_prepare_mix', 'confirm_prepare_mix',
             'begin_recipe_operation', 'confirm_recipe_operation', 'mark_recipe_unknown',
             'resolve_recipe_operation', 'resolve_prepared_output')
    RECOVERY_COMMANDS = CutRunManualSopWorkflow.RECOVERY_COMMANDS | {
        'confirm_prepare_mix', 'confirm_recipe_operation', 'mark_recipe_unknown',
        'resolve_recipe_operation', 'resolve_prepared_output'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    @classmethod
    def _load_definition(cls, source, **kwargs):
        from cutrun_manual_recipe_sources import load
        return load(source, **kwargs)

    @classmethod
    def _validate_reagent_binding(cls, inventory, source, reaction_id, item, key):
        from cutrun_manual_recipe_sources import recipe_profile
        return bindings.validate_reagent_binding(inventory, recipe_profile(source), item, key)

    @classmethod
    def _extra_state(cls, definition, reactions):
        state = super()._extra_state(definition, reactions)
        # Validate the final immutable profile, not an earlier file read in
        # the inventory hook. No run, reservation or material effect exists yet.
        roles = definition['recipe_profile']['roles']
        for reaction in reactions.values():
            if reaction['role'] == 'input':
                continue
            for field, suffix in [('activation_material_id', '.digestion_mix'),
                                  ('stop_material_id', '.stop_mix')]:
                expected = roles[reaction['role'] + suffix]['material_id']
                if expected is not None and reaction[field] != expected:
                    raise TaskError('Actual reaction reagent differs from its pinned recipe role: ' + field)
        state['recipe'] = {'engine': cls.ENGINE, 'operations': {}, 'cursors': {},
            'pending_observation': None, 'role_materials': {}, 'column_materials': {},
            'shared_steps': {}, 'consumables': {}, 'assay_materials': {}}
        return state

    @classmethod
    def _validate_format(cls, state):
        super()._validate_format(state)
        if state.get('recipe', {}).get('engine') != cls.ENGINE:
            raise TaskError('A separate wash/reagent engine is required; no SOP run migration')

    @staticmethod
    def _role(state, role):
        value = state['definition']['recipe_profile']['roles'].get(role)
        if value is None:
            raise TaskError('Unknown recipe reagent role')
        return value

    def _material_for_role(self, state, role):
        return bindings.resolve_role_material(state, role)

    def _step_list(self, state, stage):
        protocol = state['definition']['recipe_protocol']
        role = None if stage['reaction_id'] is None else state['manual']['reactions'][stage['reaction_id']]['role']
        return [item for item in protocol['stage_steps'].get(stage['stage_id'], []) if role in item['roles']]

    def _skip(self, state, step):
        profile = state['definition']['recipe_profile']
        local = profile['steps'][step['id']]
        if local['enabled'] is False:
            return True
        return step.get('execution_scope') == 'run' and step['id'] in state['recipe']['shared_steps']

    def _next(self, state, stage):
        cursors = state['recipe']['cursors'].get(stage['id'], {})
        for step in self._step_list(state, stage):
            if self._skip(state, step):
                continue
            if step['kind'] in {'activation', 'stop'}:
                reaction = state['manual']['reactions'][stage['reaction_id']]
                effect = reaction[step['kind']]
                if effect is not None and state['bookings'][effect['intent_id']]['outcome'] == 'performed':
                    continue
                return {'step_id': step['id'], 'iteration': 1, 'operation': 'adopt', 'kind': step['kind']}
            local = state['definition']['recipe_profile']['steps'][step['id']]
            cursor = cursors.get(step['id'], {'iteration': 1, 'position': 0, 'complete': False})
            if cursor['complete']:
                continue
            return {'step_id': step['id'], 'iteration': cursor['iteration'],
                    'operation': step['actions'][cursor['position']], 'kind': step['kind'],
                    'binding_open': local['enabled'] is not True or step['kind'] != 'load' and local['repeat_count'] is None}
        return None

    def recipe_next(self, stage_run_id):
        state = self.state
        stage = self._stage(state, stage_run_id)
        result = copy.deepcopy(self._next(state, stage))
        if result is not None:
            step = self._definition_step(state, stage, result['step_id'])
            result['reagent_role'] = self._reagent_role(state, stage, step)
            try:
                target = self._target(state, stage, step, result['operation'])
            except (KeyError, TaskError):
                target = None
            result['target_material_id'] = target
            result['target_vessel_id'] = None if target is None else state['inventory']['materials'][target]['vessel_id']
        return result

    def _definition_step(self, state, stage, step_id):
        step = next((item for item in self._step_list(state, stage) if item['id'] == step_id), None)
        if step is None:
            raise TaskError('Recipe step belongs to another stage or reaction')
        return step

    def _ordinary(self, state, stage):
        self._require_stage(state, stage['stage_id'], stage['reaction_id'])
        CutRunManualWorkflow._stage_ready(self, state, stage['stage_id'])
        if state['recipe']['pending_observation'] is not None:
            raise TaskError('Resolve the pending physical recipe observation before new work')
        if any(item['status'] in {'possibly_active', 'active', 'stop_unconfirmed'}
               for item in state['manual']['reactions'].values()):
            raise TaskError('Protect the active serial-pilot reaction before ordinary recipe work')

    @staticmethod
    def _known_source(state, identity, quantity):
        amount = ledger.quantity(quantity, units={'uL'})
        balance = ledger.remaining(state, identity)
        if amount['value'] is None or balance['value'] is None or balance['unit'] != 'uL':
            raise TaskError('Known actual source balance and a bound dose required for a new instruction')
        if amount['value'] > balance['value'] + 1e-9:
            raise TaskError('Insufficient recorded recipe reagent or source mixture')
        return amount

    def _begin_prepare_mix(self, state, actor_id, stage_run_id, recipe_role, intent_id):
        stage = self._stage(state, stage_run_id)
        self._ordinary(state, stage)
        role = self._role(state, recipe_role)
        if role['mode'] != 'prepared':
            raise TaskError('An issued working reagent must not be prepared and charged again')
        if (role['output_quantity']['value'] is None
                or any(role.get(key) is None for key in ('preparation_ref', 'evidence_ref'))):
            raise TaskError('Prospective preparation yield/reference bindings remain open')
        if role['material_id'] in state['inventory']['materials']:
            raise TaskError('The planned working mixture already exists')
        if recipe_role == 'working.activated_beads':
            following = self._next(state, stage)
            if not following or following['step_id'] != 'S03.bead_resuspension' or following['operation'] != 'add':
                raise TaskError('Complete the bead washes before its final resuspension/preparation')
            step_dose = state['definition']['recipe_profile']['steps']['S03.bead_resuspension']['quantity']
            if role['components']['stock.bead_activation_buffer'] != step_dose:
                raise TaskError('The final bead resuspension dose and preparation component must agree')
        component_materials, inputs = {}, []
        for component, quantity in role['components'].items():
            identity = self._material_for_role(state, component)
            if not bindings.reagent_ready(state, component):
                raise TaskError('A preparation component is not ready: ' + component)
            component_materials[component] = identity
            inputs.append({'material_id': identity, 'quantity': self._known_source(state, identity, quantity), 'consume_all': False})
        output = {'material_id': role['material_id'], 'kind': 'intermediate',
                  'vessel_id': role['vessel_id'], 'role': 'working_reagent'}
        changed = ledger.begin_effect(state, actor_id, intent_id, 'transformation', inputs, [output],
                                      'recipe_preparation:' + recipe_role)
        if changed is False:
            return False
        state['manual']['actions'][intent_id] = {'operation': 'recipe_preparation', 'recipe_role': recipe_role,
            'component_materials': component_materials, 'stage_run_id': stage_run_id, 'stage_id': stage['stage_id'],
            'reaction_id': stage['reaction_id'], 'retained_material_id': role['material_id']}
        state['recipe']['operations'][intent_id] = {'kind': 'preparation', 'stage_run_id': stage_run_id,
            'recipe_role': recipe_role, 'outcome': 'intent', 'intent_receipt': material_evidence.receipt(state, actor_id, 'Working reagent preparation intent')}
        self._after_material_change(state, True)

    def _confirm_prepare_mix(self, state, actor_id, intent_id, actual_inputs, actual_outputs, reason):
        item = state['recipe']['operations'].get(intent_id)
        if item is None or item['kind'] != 'preparation':
            raise TaskError('Matching preparation intent required')
        if state['recovery_required'] and not getattr(self, '_resolving_recipe', False):
            raise TaskError('Explicit recipe reconciliation is required for a held preparation')
        if any(entry['quantity']['unit'] != 'uL' for entry in actual_outputs):
            raise ObservationError('A working liquid mixture needs an observed volume with unit uL')
        changed = ledger.confirm_effect(state, actor_id, intent_id, actual_inputs, actual_outputs, reason)
        if changed is False:
            return False
        item = state['recipe']['operations'][intent_id]
        item['outcome'], item['receipt'] = 'performed', material_evidence.receipt(state, actor_id, reason)
        if not bindings.reagent_ready(state, item['recipe_role']):
            self._hold(state, 'recipe_preparation_uncertain', 'Actual preparation differs from its known recipe: ' + intent_id)
        if item.get('step_id'):
            self._advance(state, item)
        self._after_material_change(state, True)

    def _target(self, state, stage, step, operation):
        if step['id'] == 'S03.bead_resuspension' and operation == 'mix':
            return self._material_for_role(state, 'working.activated_beads')
        if step['target_role'] == 'assay.permeabilization':
            return state['recipe']['assay_materials'][stage['reaction_id']]
        if step['target_role'] is not None:
            return self._material_for_role(state, step['target_role'])
        reaction_id = stage['reaction_id']
        if step['kind'] == 'load' and operation != 'load':
            return state['recipe']['column_materials'][reaction_id]
        return state['manual']['reactions'][reaction_id]['current_material_id']

    def _reagent_role(self, state, stage, step):
        role = step['reagent_role']
        if isinstance(role, dict):
            role = role[state['manual']['reactions'][stage['reaction_id']]['role']]
        return role

    def _begin_recipe_operation(self, state, actor_id, stage_run_id, step_id, iteration, operation, intent_id,
                                outputs=None, retained_material_id=None, source_quantity=None):
        stage = self._stage(state, stage_run_id)
        self._ordinary(state, stage)
        following = self._next(state, stage)
        if following is None or any(following[key] != value for key, value in
                {'step_id': step_id, 'iteration': iteration, 'operation': operation}.items()):
            raise TaskError('Complete the exact preceding recipe operation and cycle first')
        if operation == 'adopt':
            raise TaskError('Use the existing activation/stop intent and receipt; do not book a second dose')
        step = self._definition_step(state, stage, step_id)
        if step_id == 'S03.bead_resuspension' and operation == 'add':
            self._begin_prepare_mix(state, actor_id, stage_run_id, 'working.activated_beads', intent_id)
            item = state['recipe']['operations'][intent_id]
            item.update(step_id=step_id, iteration=iteration, operation=operation)
            return
        text(intent_id, 'recipe effect identity')
        if intent_id in state['recipe']['operations'] or intent_id in state['manual']['actions']:
            raise TaskError('Recipe effect identity already used; reconcile the original intent')
        target_id = self._target(state, stage, step, operation)
        target = state['inventory']['materials'][target_id]
        item = {'kind': 'observation' if operation in {'mix', 'separate', 'dry', 'observe'} else 'material',
            'stage_run_id': stage_run_id, 'step_id': step_id, 'iteration': iteration, 'operation': operation,
            'target_material_id': target_id, 'outcome': 'intent', 'intent_receipt': material_evidence.receipt(state, actor_id, 'Recipe operation intent')}
        if item['kind'] == 'observation':
            if outputs or retained_material_id is not None or source_quantity is not None:
                raise TaskError('Mixing/separation/drying has no invented quantity effect')
            if operation == 'observe':
                checksum = state['observation_context']['artifact_sha256']
                if checksum is None:
                    raise TaskError('The manual permeability observation requires an archived original result')
                self._owned_original(state, checksum)
            state['recipe']['pending_observation'] = intent_id
        else:
            if not isinstance(outputs, list) or not outputs or retained_material_id not in {out['material_id'] for out in outputs}:
                raise TaskError('Explicit new retained and removed fraction identities required')
            retained = next(out for out in outputs if out['material_id'] == retained_material_id)
            if operation == 'load':
                reaction_role = state['manual']['reactions'][stage['reaction_id']]['role']
                consumable = state['definition']['recipe_profile']['consumables'][reaction_role]
                column = consumable['column_id']
                if retained['vessel_id'] != column or len(outputs) != 1 or retained['kind'] != 'intermediate':
                    raise TaskError('A load retains one explicit wet fraction in its bound physical column')
                old_owner = state['recipe']['consumables'].get(column)
                if old_owner not in (None, stage['reaction_id']):
                    raise TaskError('The column is assigned to another reaction')
                cap = state['definition']['recipe_profile']['steps'][step_id]['quantity']['value']
                remaining = ledger.remaining(state, target_id)
                if remaining['value'] is None or remaining['unit'] != 'uL':
                    raise TaskError('Column loading needs the known actual mixture remainder')
                quantity = {'value': min(cap, remaining['value']), 'unit': 'uL'} if source_quantity is None else source_quantity
                quantity = self._known_source(state, target_id, quantity)
                if quantity['value'] > cap:
                    raise TaskError('Load exceeds the locally bound column capacity')
                inputs = [{'material_id': target_id, 'quantity': quantity, 'consume_all': False}]
                column_material = state['recipe']['column_materials'].get(stage['reaction_id'])
                if column_material is not None:
                    inputs.append({'material_id': column_material, 'quantity': ledger.remaining(state, column_material), 'consume_all': True})
                    inputs[-1]['quantity'].pop('knowledge')
                state['recipe']['consumables'][column] = stage['reaction_id']
            else:
                amount = ledger.remaining(state, target_id)
                inputs = [{'material_id': target_id, 'quantity': {'value': amount['value'], 'unit': amount['unit']}, 'consume_all': True}]
                if operation == 'split':
                    role = state['manual']['reactions'][stage['reaction_id']]['role']
                    vessel = state['definition']['recipe_profile']['consumables'][role]['permeabilization_vessel_id']
                    if (len(outputs) != 2 or retained['kind'] != 'intermediate'
                            or retained['vessel_id'] != target['vessel_id']):
                        raise TaskError('Assay splitting retains the original sample in its current vessel')
                    assay = next(out for out in outputs if out['material_id'] != retained_material_id)
                    if assay['kind'] != 'intermediate' or assay['vessel_id'] != vessel or assay['role'] != 'permeabilization_aliquot':
                        raise TaskError('An identified assay aliquot must reach its bound actual test vessel')
                    item['assay_material_id'] = assay['material_id']
                elif operation == 'add':
                    role = self._reagent_role(state, stage, step)
                    if not bindings.reagent_ready(state, role):
                        raise TaskError('Bound working reagent is unprepared, uncertain or has conflicting provenance')
                    reagent = self._material_for_role(state, role)
                    quantity = state['definition']['recipe_profile']['steps'][step_id]['quantity']
                    inputs.append({'material_id': reagent, 'quantity': self._known_source(state, reagent, quantity), 'consume_all': False})
                    item['reagent_material_id'] = reagent
                    item['reagent_role'] = role
                    if len(outputs) != 1 or retained['vessel_id'] != target['vessel_id'] or retained['kind'] != 'intermediate':
                        raise TaskError('Addition creates one wet intermediate in the identified target vessel')
                elif operation == 'remove':
                    if len(outputs) != 2 or len({out['vessel_id'] for out in outputs}) != 2:
                        raise TaskError('Removal needs retained and removed fractions in separate identified vessels')
                    removed = next(out for out in outputs if out['material_id'] != retained_material_id)
                    if removed['kind'] != 'byproduct':
                        raise TaskError('The removed fraction must remain an identified byproduct')
                    for label, output in [('retained', retained), ('removed', removed)]:
                        expected_role = step['source_facts'].get(label)
                        if expected_role is not None and output['role'] != expected_role:
                            raise TaskError('Retained/removed phase role differs from the pinned recipe')
                    if step['kind'] == 'elute':
                        role = state['manual']['reactions'][stage['reaction_id']]['role']
                        if retained['kind'] != 'product' or retained['vessel_id'] != state['definition']['recipe_profile']['consumables'][role]['elution_vessel_id']:
                            raise TaskError('The eluate must reach its bound actual product vessel')
                        if removed['vessel_id'] != target['vessel_id']:
                            raise TaskError('The spent column must keep its actual column identity')
                    elif retained['kind'] != 'intermediate':
                        raise TaskError('A wash/removal retains an identified intermediate, not a final product')
                    elif step_id in {'S08.released_fraction', 'S09.clarified_fraction'}:
                        if retained['vessel_id'] == target['vessel_id'] or removed['vessel_id'] != target['vessel_id']:
                            raise TaskError('The retained supernatant needs its actual new vessel; solids remain in the source')
                    elif retained['vessel_id'] != target['vessel_id']:
                        raise TaskError('The washed pellet/beads/column remain in their identified target vessel')
                else:
                    raise TaskError('Unsupported recipe material operation')
            changed = ledger.begin_effect(state, actor_id, intent_id, 'transformation', inputs, outputs,
                                          'recipe_operation:' + step_id + ':' + operation)
            if changed is False:
                return False
            state['manual']['actions'][intent_id] = {'operation': 'recipe_material', 'recipe_step_id': step_id,
                'recipe_target_role': step['target_role'], 'retained_material_id': retained_material_id,
                'stage_run_id': stage_run_id, 'stage_id': stage['stage_id'], 'reaction_id': stage['reaction_id']}
            item['retained_material_id'] = retained_material_id
            self._after_material_change(state, True)
        state['recipe']['operations'][intent_id] = item

    def _advance(self, state, item):
        stage = self._stage(state, item['stage_run_id'])
        step = self._definition_step(state, stage, item['step_id'])
        entries = state['recipe']['cursors'].setdefault(stage['id'], {})
        cursor = entries.setdefault(step['id'], {'iteration': 1, 'position': 0, 'complete': False})
        cursor['position'] += 1
        if cursor['position'] == len(step['actions']):
            cursor['position'] = 0
            local = state['definition']['recipe_profile']['steps'][step['id']]
            if step['kind'] == 'load':
                source = state['recipe'].setdefault('load_sources', {}).get(stage['id'])
                balance = ledger.remaining(state, source) if source else {'value': None}
                finished = balance['value'] is not None and abs(balance['value']) < 1e-9
                if finished:
                    state['manual']['reactions'][stage['reaction_id']]['current_material_id'] = state['recipe']['column_materials'][stage['reaction_id']]
            else:
                finished = cursor['iteration'] >= local['repeat_count']
            if finished:
                cursor['complete'] = True
                if step.get('execution_scope') == 'run':
                    state['recipe']['shared_steps'][step['id']] = {'stage_run_id': stage['id'], 'receipt': copy.deepcopy(item['receipt'])}
            else:
                cursor['iteration'] += 1

    def _confirm_recipe_operation(self, state, actor_id, intent_id, actual_inputs, actual_outputs, observations, reason):
        item = state['recipe']['operations'].get(intent_id)
        if item is None or item['kind'] == 'preparation':
            raise TaskError('Matching recipe operation intent required')
        if state['recovery_required'] and not getattr(self, '_resolving_recipe', False):
            raise TaskError('Explicit recipe reconciliation is required for a held or rejected effect')
        if item['outcome'] == 'performed':
            raise TaskError('Reuse the original observation identity for an unchanged receipt')
        if item['outcome'] == 'not_performed':
            raise TaskError('A resolved nonperformed action cannot later become performed')
        if not isinstance(observations, dict):
            raise TaskError('Explicit physical observations required')
        if item['kind'] == 'observation':
            field = {'mix': 'mixed', 'separate': 'separated', 'dry': 'dried', 'observe': 'observed'}[item['operation']]
            if actual_inputs != [] or actual_outputs != []:
                raise TaskError('A physical observation cannot fabricate material quantities')
            if observations != {'performed': True, field: True}:
                self._hold(state, 'recipe_observation_unknown', 'Physical effect remains unconfirmed: ' + intent_id)
                item['outcome'] = 'unknown'
                item['receipt'] = material_evidence.receipt(state, actor_id, reason, observations=copy.deepcopy(observations))
                return
            state['recipe']['pending_observation'] = None
        else:
            changed = ledger.confirm_effect(state, actor_id, intent_id, actual_inputs, actual_outputs, reason)
            if changed is False:
                return False
            item = state['recipe']['operations'][intent_id]
            stage = self._stage(state, item['stage_run_id'])
            step = self._definition_step(state, stage, item['step_id'])
            retained = item['retained_material_id']
            if step['target_role'] == 'assay.permeabilization':
                state['recipe']['assay_materials'][stage['reaction_id']] = retained
            elif step['target_role'] is not None:
                state['recipe']['role_materials'][step['target_role']] = retained
            elif step['kind'] == 'load':
                state['recipe']['column_materials'][stage['reaction_id']] = retained
                state['recipe'].setdefault('load_sources', {}).setdefault(stage['id'], item['target_material_id'])
            else:
                state['manual']['reactions'][stage['reaction_id']]['current_material_id'] = retained
                if item['operation'] == 'split':
                    state['recipe']['assay_materials'][stage['reaction_id']] = item['assay_material_id']
            self._after_material_change(state, True)
        item['outcome'], item['receipt'] = 'performed', material_evidence.receipt(state, actor_id, reason, observations=copy.deepcopy(observations))
        self._advance(state, item)
        issues = self._operation_issues(state, intent_id, item)
        if issues:
            self._hold(state, 'recipe_dose_deviation', intent_id + ':' + ','.join(issues))

    def _operation_issues(self, state, identity, item):
        if item['kind'] != 'material' or item['outcome'] != 'performed':
            return []
        booking = state['bookings'][identity]
        actual = {entry['material_id']: entry['quantity'] for entry in booking['actual_inputs']}
        if item['operation'] == 'add':
            reagent = item.get('reagent_material_id')
            planned = next(entry['quantity'] for entry in booking['request']['inputs'] if entry['material_id'] == reagent)
            return [] if actual.get(reagent) == planned else ['actual_reagent_dose_unknown_or_different']
        if item['operation'] == 'load':
            amount = actual[item['target_material_id']]
            cap = state['definition']['recipe_profile']['steps'][item['step_id']]['quantity']
            if amount['value'] is None or amount['unit'] != 'uL' or amount['value'] > cap['value']:
                return ['actual_column_load_unknown_or_above_capacity']
        if item['operation'] == 'split':
            actual = next(entry['quantity'] for entry in booking['actual_outputs'] if entry['material_id'] == item['assay_material_id'])
            planned = state['definition']['recipe_profile']['steps'][item['step_id']]['quantity']
            if actual != planned:
                return ['actual_assay_aliquot_volume_unknown_or_different']
        return []

    def _stage_assessment(self, state, stage):
        result = super()._stage_assessment(state, stage)
        if self._next(state, stage) is not None:
            result['issues'].append('recipe_steps_incomplete')
        for identity, item in state['recipe']['operations'].items():
            if item['stage_run_id'] == stage['id']:
                if item['outcome'] in {'intent', 'unknown'}:
                    result['issues'].append('recipe_effect_unresolved:' + identity)
                if (item['kind'] == 'preparation' and item['outcome'] == 'performed'
                        and not bindings.preparation_conformant(state, item['recipe_role'])):
                    result['issues'].append('recipe_preparation_unqualified:' + identity)
                result['issues'].extend(identity + ':' + issue for issue in self._operation_issues(state, identity, item))
        for step in self._step_list(state, stage):
            if step['kind'] not in {'activation', 'stop'}:
                continue
            effect = state['manual']['reactions'][stage['reaction_id']][step['kind']]
            if effect is not None and state['bookings'][effect['intent_id']]['outcome'] == 'performed':
                actual = state['bookings'][effect['intent_id']]['actual_inputs']
                planned = state['definition']['recipe_profile']['steps'][step['id']]['quantity']
                role = self._reagent_role(state, stage, step)
                source = self._role(state, role)['material_id']
                if actual != [{'material_id': source, 'quantity': planned}]:
                    result['issues'].append('actual_protected_recipe_dose_unknown_or_different:' + step['id'])
                if not bindings.preparation_conformant(state, role):
                    result['issues'].append('protected_source_preparation_unqualified:' + step['id'])
        result['conformant'] = not result['issues']
        return result

    def _resolve_prepared_output(self, state, actor_id, intent_id, quantity, reason):
        changed = bindings.resolve_prepared_output(state, actor_id, intent_id, quantity, reason)
        return self._after_material_change(state, changed)

    def _mark_recipe_unknown(self, state, actor_id, intent_id, reason):
        item = state['recipe']['operations'].get(intent_id)
        if item is None or item['outcome'] not in {'intent', 'unknown'}:
            raise TaskError('Matching unresolved recipe intent required')
        if item['kind'] != 'observation':
            ledger.mark_unknown(state, actor_id, intent_id, reason)
            item = state['recipe']['operations'][intent_id]
        item['outcome'] = 'unknown'
        item['uncertainty'] = material_evidence.receipt(state, actor_id, reason)
        self._hold(state, 'recipe_effect_unknown', 'Reconcile the original recipe effect: ' + intent_id)

    def _resolve_recipe_operation(self, state, actor_id, intent_id, outcome, actual_inputs, actual_outputs, observations, reason):
        if outcome == 'unknown':
            return self._mark_recipe_unknown(state, actor_id, intent_id, reason)
        item = state['recipe']['operations'].get(intent_id)
        if item is None:
            raise TaskError('Unknown recipe effect')
        if outcome == 'performed':
            method = self._confirm_prepare_mix if item['kind'] == 'preparation' else self._confirm_recipe_operation
            kwargs = {} if item['kind'] == 'preparation' else {'observations': observations}
            self._resolving_recipe = True
            try:
                return method(state, actor_id, intent_id, actual_inputs, actual_outputs, reason=reason, **kwargs)
            finally:
                self._resolving_recipe = False
        if outcome != 'not_performed':
            raise TaskError('Explicit performed/not_performed/unknown resolution required')
        if item['outcome'] not in {'intent', 'unknown'}:
            raise TaskError('A completed physical recipe receipt cannot be rewritten as nonperformance')
        if actual_inputs != [] or actual_outputs != [] or observations != {}:
            raise TaskError('Nonperformance cannot invent material effects')
        if item['kind'] != 'observation':
            ledger.not_performed(state, actor_id, intent_id, reason)
            item = state['recipe']['operations'][intent_id]
        elif state['recipe']['pending_observation'] == intent_id:
            state['recipe']['pending_observation'] = None
        item['outcome'], item['receipt'] = 'not_performed', material_evidence.receipt(state, actor_id, reason)
        self._after_material_change(state, True)

    def _begin_material_action(self, state, actor_id, **kwargs):
        raise TaskError('Use the typed recipe operation; a generic material action cannot replace a wash or reagent receipt')

    def _begin_stage(self, state, actor_id, **kwargs):
        if state['recipe']['pending_observation'] is not None:
            raise TaskError('Reconcile the pending physical recipe effect before another stage')
        return super()._begin_stage(state, actor_id, **kwargs)

    def _resolve_action(self, state, actor_id, intent_id, **kwargs):
        if intent_id in state['recipe']['operations']:
            raise TaskError('Use explicit recipe reconciliation so its physical cursor and canonical booking agree')
        return super()._resolve_action(state, actor_id, intent_id, **kwargs)

    def _begin_activation(self, state, actor_id, **kwargs):
        if state['recipe']['pending_observation'] is not None:
            raise TaskError('Reconcile the pending physical recipe effect before activation')
        reaction = state['manual']['reactions'][kwargs['reaction_id']]
        role = reaction['role'] + '.digestion_mix'
        if not bindings.reagent_ready(state, role):
            raise TaskError('The actually prepared/issued activation mixture is not ready')
        if not bindings.protected_ready(state, reaction['vessel_id']):
            raise TaskError('The actually prepared/issued protected stop source is not ready')
        return super()._begin_activation(state, actor_id, **kwargs)

    def _confirm_dose(self, state, actor_id, intent_id, actual_volume_ul, mixed, reason):
        changed = super()._confirm_dose(state, actor_id, intent_id, actual_volume_ul, mixed, reason)
        if changed is not False:
            action = state['manual']['actions'][intent_id]
            step_id = 'S07.activation' if action['operation'] == 'activation' else 'S08.stop'
            planned = state['definition']['recipe_profile']['steps'][step_id]['quantity']['value']
            if actual_volume_ul is None or actual_volume_ul != planned:
                self._hold(state, 'recipe_dose_deviation', 'Actual protected working-mixture dose differs: ' + intent_id)
        return changed

    def _reconcile(self, state, actor_id, **kwargs):
        super()._reconcile(state, actor_id, **kwargs)
        if state['recipe']['pending_observation'] is not None or any(item['outcome'] in {'intent', 'unknown'} for item in state['recipe']['operations'].values()):
            state['recovery_required'], state['workspace_clear'] = 'recipe_effect_unknown', False

    def _resolve_deviation(self, state, actor_id, **kwargs):
        if state['recipe']['pending_observation'] is not None or any(item['outcome'] in {'intent', 'unknown'} for item in state['recipe']['operations'].values()):
            raise TaskError('Resolve actual recipe effects before accepting a deviation')
        return super()._resolve_deviation(state, actor_id, **kwargs)

    def _canonical_actions(self, state, stage, action_ids):
        if not isinstance(action_ids, list) or len(action_ids) != len(set(action_ids)):
            raise TaskError('Unique canonical recipe action references required')
        records = []
        for identity in action_ids:
            action = state['manual']['actions'].get(identity)
            booking = state['bookings'].get(identity)
            if action is None or booking is None or booking['outcome'] != 'performed':
                raise TaskError('Confirmed canonical effects required')
            if action.get('operation') == 'stop' and stage['stage_id'] in {'S07', 'S08'}:
                if action['reaction_id'] != stage['reaction_id']:
                    raise TaskError('Wrong reaction stop receipt')
            elif action.get('stage_run_id') != stage['id']:
                raise TaskError('Canonical effect belongs to another stage')
            records.append((identity, action, booking))
        if self._next(state, stage) is not None:
            raise TaskError('Required wash cycles, additions, separations or actual column loads remain incomplete')
        expected = {identity for identity, operation in state['recipe']['operations'].items()
                    if operation['stage_run_id'] == stage['id'] and operation['kind'] == 'material' and operation['outcome'] == 'performed'}
        if not expected <= set(action_ids):
            raise TaskError('Link every confirmed stage recipe material effect to its completion')
        return records

    def _restored(self, state):
        if state['recipe']['pending_observation'] is not None or any(item['outcome'] in {'intent', 'unknown'} for item in state['recipe']['operations'].values()):
            raise TaskError('Reconcile every recipe material/physical effect before handover')
        return super()._restored(state)

    def _report(self, state, trace):
        report = super()._report(state, trace)
        report['recipe'] = copy.deepcopy(state['recipe'])
        report['recipe']['next_operations'] = {identity: self._next(state, stage)
            for identity, stage in state['sop']['stages'].items()}
        report['recipe']['balances_are_canonical'] = True
        report['sop']['vendor_recipe_completeness_checked'] = False
        report['recipe']['selected_wash_and_reagent_contract_checked'] = True
        report['limitations'] = [
            'Selected fresh/unfixed and VII-A recipe operations are manual evidence contracts, not equipment execution.',
            'Working mixtures and doses use the common material ledger; stock and mixture quantities are not summed as one consumption.',
            'Prepared input/stock states require explicit original evidence; unknown values and yields remain unknown.',
            'No biological, clock, temperature, concentration or apparatus qualification is inferred.']
        return report
