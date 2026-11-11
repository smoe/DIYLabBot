"""One persisted DNA inventory across NanoDrop/Qubit attempts and predilutions.

Device operations are reused through source-vessel views. Only the explicit
synthetic driver supplies observations; this module sends no device commands.
"""
import copy
import inspect
import math
import re
import uuid

from manual_tasks import TaskError, encoded, digest
from manual_workflow import ObservationError, positive, text
from dna_quantification_sources import load, SOURCE
from dna_quantification_ledger import (remaining, reserve_withdrawal,
    confirm_withdrawal, resolve_not_performed, dilution_factor, classify_input)
from dna_quantification_stages import make_context, build_adapter

FORMAT = 'solidcraftbot.dna-quantification-state/1'
TERMINAL = {'completed', 'cancelled'}


class ContextHandle:
    def __init__(self, flow, context_id): self.flow, self.context_id = flow, context_id

    @property
    def state(self): return build_adapter(self.flow, self.flow.state, self.context_id).state

    def act(self, command, actor_id, **data):
        if command == 'advance_time': return self.flow.advance_time(actor_id, **data)
        return self.flow.stage_act(self.context_id, command, actor_id, **data)

    def import_content(self, content, actor_id, file_name='synthetic-report.csv'):
        return self.flow.stage_act(self.context_id, 'import_results', actor_id,
            artifact=content, file_name=file_name, origin='synthetic_export')


class Workflow:
    def __init__(self, journal, run_id, session=None):
        self.journal, self.run_id, self.session = journal, run_id, session

    @property
    def state(self):
        state, _ = self.journal.get_current(self.run_id)
        if state.get('format') != FORMAT: raise TaskError('DNA quantification run required')
        return state

    @classmethod
    def create(cls, journal, source=None, run_id=None):
        definition = load(SOURCE if source is None else source)
        run_id = run_id or 'SYN.DNA.' + uuid.uuid4().hex[:12]
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise TaskError('Run id must use 1-64 ASCII letters, digits, dots or hyphens')
        profile = definition['profile']; session = uuid.uuid4().hex
        vessels, samples = {}, {}
        for item in sorted(profile['samples'], key=lambda s: s['rack_slot']):
            place = next(p for p in definition['rack_places']['rack'] if p['slot'] == item['rack_slot'])
            home = {'kind': 'rack', 'rack_id': profile['rack']['id'], 'place_id': place['place_id']}
            vessels[item['vessel_id']] = {
                'id': item['vessel_id'], 'kind': 'original', 'origin': 'original', 'sample_id': item['id'],
                'home': home, 'location': copy.deepcopy(home), 'initial_volume_ul': item['initial_volume_ul'],
                'external_factor': 1.0, 'content_revision': 0, 'volume_uncertain': False,
                'mass_confirmation_valid': False, 'return_confirmation': None}
            samples[item['id']] = {'id': item['id'], 'vessel_id': item['vessel_id'],
                'status': 'queued', 'attempt_ids': [], 'accepted_attempt_id': None,
                'accepted_with_flags': False}
        state = {'format': FORMAT, 'run_id': run_id, 'session': session, 'definition': definition,
                 'status': 'created', 'actor_id': None, 'clock_mode': 'synthetic_events/1',
                 'logical_time_s': 0.0, 'deadline_s': profile['parameters']['task_deadline_s'],
                 'resources': [], 'rack_ready': False, 'recovery_required': None,
                 'cancel_requested': False,
                 'inventory': {'vessels': vessels}, 'samples': samples, 'bookings': {},
                 'dilutions': {}, 'pending_dilution': None, 'attempts': {}, 'contexts': {},
                 'current_sample_id': next(iter(samples)), 'active_attempt_id': None,
                 'active_context_id': None, 'decisions': []}
        journal.create(run_id, state, immutable_definition=True)
        return cls(journal, run_id, session)

    @classmethod
    def open(cls, journal, run_id, resume=False):
        flow = cls(journal, run_id); before, revision = journal.get_current(run_id)
        if before.get('format') != FORMAT: raise TaskError('DNA quantification run required')
        flow._source_check(before)
        if before['status'] in TERMINAL: return flow
        if before['session'] is not None and not resume:
            raise TaskError('Previous session is open; explicit resume and reconciliation required')
        session = uuid.uuid4().hex
        state = copy.deepcopy(before)
        state.update(session=session, status='cancelling' if before['cancel_requested'] else 'held',
                     recovery_required=before['recovery_required'] or 'restart_reconciliation')
        journal.append(run_id, revision, 'session_reopened',
            {'resume': resume, 'evidence': 'synthetic_input'}, state)
        return cls(journal, run_id, session)

    def close(self):
        state = self.state
        if state['status'] in TERMINAL or self.session is None: return
        def update(current): current['session'] = None
        self._transition('session_closed', state['actor_id'] or 'SYN.Operator01', update, allow_held=True)
        self.session = None

    @staticmethod
    def _source_check(state):
        current = load(SOURCE.parent.parent / state['definition']['source_path'])
        if (current['source_files_sha256'] != state['definition']['source_files_sha256']
                or state['clock_mode'] != 'synthetic_events/1'):
            raise TaskError('DNA run sources/clock changed; no automatic migration')

    def _transition(self, kind, actor_id, update, payload=None, artifact=None, allow_held=False):
        text(actor_id, 'synthetic actor')
        before, revision = self.journal.get_current(self.run_id)
        if before.get('format') != FORMAT or before['status'] in TERMINAL:
            raise TaskError('Active DNA quantification run required')
        if not self.session or self.session != before['session']:
            raise TaskError('Stale DNA session; reopen and reconcile')
        self._source_check(before)
        if before['cancel_requested'] and kind not in {
                'inventory_reconciled', 'cancel_requested', 'cancel_finished',
                'session_closed', 'time_advanced', 'dilution_stock_disposed',
                'device.place', 'device.dispose_vessel', 'device.discard_import'}:
            raise TaskError('Cancellation requested; only reconciliation, return and disposal are allowed')
        if before['actor_id'] is not None and before['actor_id'] != actor_id:
            raise TaskError('DNA run is held by another actor')
        if before['recovery_required'] and not allow_held:
            raise TaskError('Explicit DNA reconciliation required: ' + before['recovery_required'])
        if before['logical_time_s'] >= before['deadline_s'] and not allow_held:
            held = copy.deepcopy(before)
            held.update(status='cancelling' if before['cancel_requested'] else 'held',
                        recovery_required=before['recovery_required'] or 'deadline_exceeded')
            self.journal.append(self.run_id, revision, 'deadline_exceeded', {}, held)
            raise TaskError('DNA process deadline exceeded')
        state = copy.deepcopy(before)
        try:
            update(state)
            self._validate_positions(state)
        except ObservationError as error:
            before.update(status='cancelling' if before['cancel_requested'] else 'held',
                          recovery_required=before['recovery_required'] or 'observation_mismatch')
            self.journal.append(self.run_id, revision, 'observation_rejected',
                {'command': kind, 'actor_id': actor_id, 'reason': str(error), **(payload or {})}, before)
            raise
        state['resources'] = self._resources(state)
        self.journal.append(self.run_id, revision, kind,
            {'actor_id': actor_id, 'evidence': 'synthetic_input', **(payload or {})}, state, artifact=artifact)
        return state

    @staticmethod
    def _resources(state):
        if not state['rack_ready'] or state['status'] in TERMINAL: return []
        profile = state['definition']['profile']
        resources = ['workspace:' + state['definition']['work_area']['id'],
            'rack:' + profile['rack']['id'], 'rack:' + profile['dilution_rack']['id'],
            'reagent:' + profile['diluent']['id']]
        resources += ['instrument:' + d['profile']['instrument']['id'] for d in state['definition']['devices'].values()]
        resources += ['vessel:' + key for key, vessel in state['inventory']['vessels'].items()
                      if vessel['location']['kind'] != 'discarded']
        return sorted(set(resources))

    @staticmethod
    def _validate_positions(state):
        occupied = set(); held = 0
        logical = state['definition']['devices']['qubit']['profile']['logical_places']
        for vessel in state['inventory']['vessels'].values():
            location = vessel['location']; kind = location.get('kind')
            fields = {'discarded': {'kind'}, 'operator': {'kind', 'actor_id'},
                      'rack': {'kind', 'rack_id', 'place_id'},
                      'logical': {'kind', 'holder_id', 'place_id'}}
            if kind not in fields or set(location) != fields[kind]:
                raise ObservationError('Explicit physical location fields required; extra fields are not place identity')
            if kind == 'discarded':
                if vessel['kind'] == 'original': raise ObservationError('Original DNA vessel cannot be discarded')
                continue
            if kind == 'operator':
                if location.get('actor_id') != state['actor_id']: raise ObservationError('Wrong vessel holder')
                held += 1
            elif kind == 'rack':
                if location != vessel.get('home'): raise ObservationError('Vessel must use its declared home rack place')
            elif kind == 'logical':
                if vessel['kind'] in {'original', 'dilution'} or {'holder_id': location.get('holder_id'), 'place_id': location.get('place_id')} not in logical:
                    raise ObservationError('Unknown assay place')
            else: raise ObservationError('Unknown physical vessel location')
            key = encoded(location)
            if key in occupied or held > 1: raise ObservationError('Duplicate occupied place or multiple held vessels')
            occupied.add(key)

    def inventory_observations(self):
        return [{'vessel_id': key, 'location': copy.deepcopy(v['location']),
                 **({'sample_id': v['sample_id']} if v.get('sample_id') else {})}
                for key, v in self.state['inventory']['vessels'].items()]

    @staticmethod
    def _observations(state, observations):
        vessels = state['inventory']['vessels']
        if not isinstance(observations, list) or len(observations) != len(vessels):
            raise ObservationError('Complete DNA vessel observations required')
        seen = set()
        for item in observations:
            key = item.get('vessel_id') if isinstance(item, dict) else None
            if key not in vessels or key in seen: raise ObservationError('Unknown, duplicate or missing vessel identity')
            vessel = vessels[key]
            if vessel.get('sample_id') and item.get('sample_id') != vessel['sample_id']:
                raise ObservationError('Observed DNA sample identity mismatch')
            if not isinstance(item.get('location'), dict): raise ObservationError('Explicit physical location required')
            vessel['location'] = copy.deepcopy(item['location'])
            if vessel['location'].get('kind') == 'discarded' and vessel['kind'] != 'original':
                vessel['disposition_confirmation'] = {'actor_id': state['actor_id'],
                    'evidence': 'synthetic_input', 'reason': 'Explicit disposal observation during root inventory reconciliation'}
            if vessel['location'] == vessel.get('home'):
                vessel['return_confirmation'] = {'evidence': 'synthetic_input', 'time_s': state['logical_time_s']}
            seen.add(key)

    def accept_rack(self, actor_id, observations, workspace_clear=True, rack_on_table_confirmed=True):
        def update(state):
            if state['status'] != 'created': raise TaskError('Input rack was already accepted')
            if workspace_clear is not True or rack_on_table_confirmed is not True:
                raise ObservationError('Confirm rack on table and clear work area')
            state['actor_id'] = actor_id
            self._observations(state, observations)
            if any(v['location'] != v['home'] for v in state['inventory']['vessels'].values()):
                raise ObservationError('Initial original-rack manifest mismatch')
            state.update(rack_ready=True, status='awaiting_choice')
        return self._transition('rack_accepted', actor_id, update,
            {'observations': observations, 'rack_on_table_confirmed': rack_on_table_confirmed})

    def options(self, sample_id=None):
        return self._options(self.state, sample_id)

    @staticmethod
    def _options(state, sample_id=None):
        sample_id = sample_id or state['current_sample_id']
        if (not state['rack_ready'] or state['status'] in {'created', 'held', 'cancelling'}
                or not sample_id or sample_id != state['current_sample_id'] or state['recovery_required']):
            return []
        sample = state['samples'][sample_id]
        attempts = [state['attempts'][key] for key in sample['attempt_ids']]
        presets = state['definition']['protocol']['dilution_presets']
        if len(attempts) >= state['definition']['protocol']['repeat_policy']['max_attempts_per_sample']:
            return []
        allowed = set(presets) - {a['preset'] for a in attempts if a['status'] != 'not_performed'}
        if attempts and attempts[-1]['status'] != 'not_performed':
            evaluations = attempts[-1]['evaluations']; statuses = {r['status'] for r in evaluations.values()}
            if 'unknown' in statuses or not statuses: return []
            if 'above_range' in statuses and 'below_range' not in statuses:
                allowed = {p for p in allowed if presets[p]['factor'] > attempts[-1]['external_factor']}
            elif 'below_range' in statuses and 'above_range' not in statuses:
                allowed &= {'none'}
            else: return []
        return [{'key': name, 'label': presets[name]['label_de'], 'factor': presets[name]['factor']}
                for name in presets if name in allowed]

    def choose_dilution(self, actor_id, sample_id, preset):
        def update(state):
            if state['active_context_id'] or state['pending_dilution']:
                raise TaskError('Finish the current operation before another dilution')
            if preset not in {p['key'] for p in self._options(state, sample_id)}:
                raise TaskError('Dilution choice is unavailable; low/unknown results cannot be diluted further')
            sample = state['samples'][sample_id]; original = state['inventory']['vessels'][sample['vessel_id']]
            if original['location'] != original['home'] or original['volume_uncertain']:
                raise TaskError('Returned original with resolved consumption required')
            if state['active_attempt_id']:
                state['attempts'][state['active_attempt_id']]['status'] = 'superseded'
            attempt_id = self.run_id + '.' + sample_id + '.A%02d' % (len(sample['attempt_ids']) + 1)
            attempt = {'id': attempt_id, 'sample_id': sample_id, 'preset': preset,
                'input_vessel_id': sample['vessel_id'], 'external_factor': 1.0,
                'contexts': {}, 'evaluations': {}, 'results': {}, 'status': 'active'}
            state['attempts'][attempt_id] = attempt; sample['attempt_ids'].append(attempt_id)
            state['active_attempt_id'] = attempt_id; sample['status'] = 'measuring'
            if preset == 'none': self._start_context(state, attempt, 'nanodrop'); return
            places = state['definition']['rack_places']['dilution_rack']
            rack_id = state['definition']['profile']['dilution_rack']['id']
            occupied = [v['location'] for v in state['inventory']['vessels'].values()]
            home = next(({'kind': 'rack', 'rack_id': rack_id, 'place_id': p['place_id']}
                         for p in places if {'kind': 'rack', 'rack_id': rack_id, 'place_id': p['place_id']} not in occupied), None)
            if home is None: raise TaskError('No free dilution-rack place; dispose a retired stock explicitly')
            target_id = attempt_id + '.Dilution'; intent_id = uuid.uuid4().hex
            if target_id in state['inventory']['vessels']:
                raise TaskError('Dilution vessel identity was already used')
            volume = state['definition']['profile']['parameters']['dilution_sample_volume_ul']
            rule = state['definition']['protocol']['dilution_presets'][preset]
            pending = {'intent_id': intent_id, 'attempt_id': attempt_id, 'sample_id': sample_id,
                'source_vessel_id': sample['vessel_id'], 'target_vessel_id': target_id, 'preset': preset,
                'planned_sample_volume_ul': volume, 'planned_diluent_volume_ul': volume * rule['diluent_parts']}
            state['inventory']['vessels'][target_id] = {'id': target_id, 'kind': 'dilution', 'origin': 'derived',
                'sample_id': sample_id, 'parent_vessel_id': sample['vessel_id'], 'home': home,
                'location': copy.deepcopy(home), 'initial_volume_ul': None, 'content_revision': 0,
                'volume_uncertain': True, 'mass_confirmation_valid': False, 'return_confirmation': None,
                'content_state': 'pending', 'external_factor': None}
            reserve_withdrawal(state, intent_id=intent_id, source_vessel_id=sample['vessel_id'],
                planned_volume_ul=volume, stage_id='dilution', attempt_id=attempt_id,
                target={'kind': 'vessel', 'vessel_id': target_id}, actor_id=actor_id)
            state['pending_dilution'] = pending; state['status'] = 'running'
        return self._transition('dilution_selected', actor_id, update, {'sample_id': sample_id, 'preset': preset})

    @staticmethod
    def _start_context(state, attempt, device):
        context = make_context(state, device, attempt['id'], attempt['sample_id'], attempt['input_vessel_id'])
        attempt['contexts'][device] = context['id']
        state.update(active_context_id=context['id'], status='running')

    def _finish_dilution(self, state, actor_id, intent_id, observed_source_vessel_id,
                         observed_target_vessel_id, sample_volume_ul, diluent_volume_ul,
                         mixed, source_returned, deviation_reason=None):
        pending = state['pending_dilution']
        if not pending or pending['intent_id'] != intent_id: raise TaskError('Unknown or stale dilution intent')
        if (observed_source_vessel_id != pending['source_vessel_id']
                or observed_target_vessel_id != pending['target_vessel_id']):
            raise ObservationError('Dilution source or target identity mismatch')
        if mixed is not True or source_returned is not True:
            raise ObservationError('Mixing and original-rack return must be confirmed')
        source = state['inventory']['vessels'][pending['source_vessel_id']]
        target = state['inventory']['vessels'][pending['target_vessel_id']]
        if source['location'] != source['home'] or target['location'] != target['home']:
            raise ObservationError('Observe original and dilution stock at their declared rack places')
        factor = dilution_factor(sample_volume_ul, diluent_volume_ul)
        if not math.isclose(diluent_volume_ul, pending['planned_diluent_volume_ul'], abs_tol=1e-9):
            text(deviation_reason, 'diluent-volume deviation reason')
        confirm_withdrawal(state, intent_id, sample_volume_ul, reason=deviation_reason)
        target.update(initial_volume_ul=sample_volume_ul + diluent_volume_ul, external_factor=factor,
                      volume_uncertain=False, content_state='mixed',
                      dilution={'sample_volume_ul': sample_volume_ul, 'diluent_volume_ul': diluent_volume_ul,
                                'diluent_id': state['definition']['profile']['diluent']['id'],
                                'nominal_preset': pending['preset'], 'actual_factor': factor})
        source['return_confirmation'] = {'actor_id': actor_id, 'evidence': 'synthetic_input'}
        state['dilutions'][intent_id] = {**pending, **target['dilution'], 'actor_id': actor_id,
                                       'evidence': 'synthetic_input', 'confirmed_at_s': state['logical_time_s']}
        attempt = state['attempts'][pending['attempt_id']]
        attempt.update(input_vessel_id=target['id'], external_factor=factor)
        state['pending_dilution'] = None
        if state['cancel_requested']:
            attempt['status'] = 'cancelled_after_dilution'
            return
        self._start_context(state, attempt, 'nanodrop')

    def confirm_dilution(self, actor_id, **data):
        return self._transition('dilution_confirmed', actor_id,
            lambda state: self._finish_dilution(state, actor_id, **data), data)

    def stage(self, context_id): return ContextHandle(self, context_id)

    def stage_act(self, context_id, command, actor_id, artifact=None, **data):
        def update(state):
            if context_id != state['active_context_id']: raise TaskError('Retired or inactive device context')
            adapter = build_adapter(self, state, context_id); view = adapter.state
            if command in {'rack_ready', 'advance_time', 'release', 'cancel', 'finish_cancel', 'reconcile'}:
                raise TaskError('Use the root lifecycle, clock and reconciliation commands')
            allowed = set(view['definition']['protocol']['steps']) | {'take', 'discard_import'}
            if command not in allowed: raise TaskError('Unknown device operation: ' + command)
            if view['actor_id'] is not None and view['actor_id'] != actor_id: raise TaskError('Wrong device actor')
            before = copy.deepcopy(adapter._pending(view))
            handler = getattr(adapter, '_' + command)
            args = {'artifact': artifact, **data} if command == 'import_results' else {'actor_id': actor_id, **data}
            try: inspect.signature(handler).bind(view, **args)
            except TypeError as error: raise TaskError('Invalid device arguments: ' + str(error)) from error
            handler(view, **args)
            pending = adapter._pending(view)
            if pending and not before:
                device = state['contexts'][context_id]['device']
                source_operation = device == 'nanodrop' or (pending['kind'] == 'preparation'
                    and view['preparations'][pending['preparation_id']]['kind'] == 'sample')
                if source_operation:
                    context = state['contexts'][context_id]
                    reserve_withdrawal(state, intent_id=pending['intent_id'],
                        source_vessel_id=context['source_vessel_id'],
                        planned_volume_ul=view['definition']['profile']['parameters']['sample_volume_ul'],
                        stage_id=context_id, attempt_id=context['attempt_id'],
                        target={'kind': 'discarded_after_cleanup'} if device == 'nanodrop' else
                               {'kind': 'vessel', 'vessel_id': pending['vessel_id']}, actor_id=actor_id)
        return self._transition('device.' + command, actor_id, update,
            {'context_id': context_id, **data}, artifact=artifact,
            allow_held=command in {'place', 'dispose_vessel', 'discard_import'})

    def advance_time(self, actor_id, seconds):
        positive(seconds, 'synthetic elapsed seconds')
        def update(state):
            state['logical_time_s'] += seconds
            if state['logical_time_s'] >= state['deadline_s']:
                state.update(status='cancelling' if state['status'] == 'cancelling' else 'held',
                             recovery_required=state['recovery_required'] or 'deadline_exceeded')
        return self._transition('time_advanced', actor_id, update, {'seconds': seconds}, allow_held=True)

    def finish_context(self, actor_id, context_id, workspace_clear=True):
        def update(state):
            if context_id != state['active_context_id']: raise TaskError('Inactive or retired context')
            adapter = build_adapter(self, state, context_id); view = adapter.state
            if workspace_clear is not True or adapter._pending(view): raise TaskError('Resolved operation and clear workspace required')
            adapter._restored(view)
            adapter._before_import(view)
            adapter._scientific_ready(view)
            if any(item['status'] == 'quarantined' for item in view['imports'].values()):
                raise TaskError('Resolve quarantined imports before leaving device')
            if set(view['results']) != adapter._expected_results(view): raise TaskError('All identified results required')
            adapter._verify_artifacts(view)
            context = state['contexts'][context_id]; device = context['device']
            sample_results = [r for r in view['results'].values() if r.get('sample_id') == context['sample_id']]
            if len(sample_results) != 1: raise TaskError('Exactly one source result per device context required')
            result = copy.deepcopy(sample_results[0]); sample_volume = total_volume = None
            if device == 'qubit':
                preparation = view['preparations'][result['preparation_id']]
                sample_volume, total_volume = preparation['sample_volume_ul'], preparation['assay_total_volume_ul']
            else:
                sample_volume = view['measurements'][result['measurement_id']]['withdrawn_volume']['value']
            attempt = state['attempts'][context['attempt_id']]
            evaluation = classify_input(result, device, state['definition']['protocol']['assays'][device],
                sample_volume_ul=sample_volume, total_volume_ul=total_volume,
                external_factor=attempt['external_factor'])
            attempt['results'][device] = result; attempt['evaluations'][device] = evaluation
            view.local.update(status='completed', workspace_clear=True, session=None)
            state['active_context_id'] = None
            if device == 'nanodrop' and evaluation['status'] != 'above_range':
                self._start_context(state, attempt, 'qubit')
            else:
                attempt['status'] = 'awaiting_decision'
                state['status'] = 'awaiting_choice' if evaluation['status'] == 'above_range' else 'awaiting_decision'
        return self._transition('device_context_finished', actor_id, update, {'context_id': context_id})

    def accept_result(self, actor_id, sample_id, allow_unquantified=False, reason=None):
        def update(state):
            if state['active_context_id'] or state['pending_dilution'] or sample_id != state['current_sample_id']:
                raise TaskError('Complete the current paired measurement first')
            attempt = state['attempts'][state['active_attempt_id']]
            if set(attempt['evaluations']) != {'nanodrop', 'qubit'}:
                raise TaskError('NanoDrop and Qubit results are both required')
            flagged = any(v['status'] != 'in_range' for v in attempt['evaluations'].values())
            if flagged and (allow_unquantified is not True or not isinstance(reason, str) or not reason.strip()):
                raise TaskError('Out-of-range or unknown result needs dilution or explicit unquantified review')
            sample = state['samples'][sample_id]
            sample.update(status='accepted', accepted_attempt_id=attempt['id'], accepted_with_flags=flagged)
            attempt['status'] = 'accepted_with_flags' if flagged else 'accepted'
            state['decisions'].append({'sample_id': sample_id, 'attempt_id': attempt['id'],
                'allow_unquantified': flagged, 'reason': reason, 'evidence': 'synthetic_input'})
            state['current_sample_id'] = next((key for key, value in state['samples'].items() if value['status'] == 'queued'), None)
            state.update(active_attempt_id=None, status='awaiting_choice' if state['current_sample_id'] else 'awaiting_decision')
        return self._transition('paired_result_reviewed', actor_id, update,
            {'sample_id': sample_id, 'allow_unquantified': allow_unquantified, 'reason': reason})

    def dispose_material(self, actor_id, vessel_id, observed_vessel_id, reason):
        text(reason, 'disposal reason')
        def update(state):
            vessel = state['inventory']['vessels'].get(vessel_id)
            if (not vessel or vessel['kind'] != 'dilution' or vessel_id != observed_vessel_id
                    or vessel['location'] != vessel['home'] or state['active_context_id'] or state['pending_dilution']):
                raise TaskError('Only a returned, unused dilution stock can be disposed here')
            vessel['disposed_remaining_volume_ul'] = remaining(state, vessel_id)
            vessel.update(location={'kind': 'discarded'}, disposition_confirmation={
                'actor_id': actor_id, 'reason': reason, 'evidence': 'synthetic_input'})
        return self._transition('dilution_stock_disposed', actor_id, update, {'vessel_id': vessel_id, 'reason': reason})

    @staticmethod
    def _closed_inventory(state):
        if state['pending_dilution'] or state['active_context_id']: raise TaskError('Pending device/dilution context blocks completion')
        if any(b['outcome'] in {'intent', 'unknown'} for b in state['bookings'].values()): raise TaskError('Unresolved withdrawal blocks completion')
        for vessel in state['inventory']['vessels'].values():
            if vessel['kind'] == 'original':
                if vessel['location'] != vessel['home'] or not vessel['return_confirmation']:
                    raise ObservationError('Return every original to its original rack place')
            elif vessel['location']['kind'] != 'discarded':
                raise ObservationError('Explicit disposal of every derived vessel is required')

    def complete(self, actor_id, observations, workspace_clear=True):
        def update(state):
            if workspace_clear is not True: raise ObservationError('Clear work area confirmation required')
            if any(s['status'] != 'accepted' for s in state['samples'].values()): raise TaskError('Review every paired result first')
            self._observations(state, observations); self._closed_inventory(state)
            self._audit(state)
            state.update(status='completed', session=None)
        return self._transition('run_completed', actor_id, update, {'observations': observations})

    def reconcile(self, actor_id, observations, workspace_clear, pending_resolution=None,
                  calibration_still_valid=False, blank_still_valid=False):
        def update(state):
            if workspace_clear is not True: raise ObservationError('Explicit work-area observation required')
            cancelling = state['cancel_requested']
            self._observations(state, observations)
            if state['pending_dilution']:
                pending = state['pending_dilution']
                if not isinstance(pending_resolution, dict) or pending_resolution.get('intent_id') != pending['intent_id']:
                    raise TaskError('Matching dilution outcome required')
                outcome = pending_resolution.get('outcome')
                if outcome == 'performed':
                    self._finish_dilution(state, actor_id, **{k:v for k,v in pending_resolution.items() if k != 'outcome'})
                elif outcome == 'not_performed':
                    resolve_not_performed(state, pending['intent_id'])
                    vessel = state['inventory']['vessels'][pending['target_vessel_id']]
                    vessel.update(content_state='empty', initial_volume_ul=0.0, volume_uncertain=False)
                    state['attempts'][pending['attempt_id']]['status'] = 'not_performed'
                    state['pending_dilution'] = None
                elif outcome == 'unknown':
                    state['bookings'][pending['intent_id']]['outcome'] = 'unknown'
                    state.update(status='cancelling' if cancelling else 'held',
                                 recovery_required='dilution_outcome_unknown'); return
                else: raise TaskError('Explicit dilution outcome required')
            elif state['active_context_id']:
                adapter = build_adapter(self, state, state['active_context_id']); view = adapter.state
                before = copy.deepcopy(adapter._pending(view))
                kwargs = {'calibration_still_valid': calibration_still_valid} if state['contexts'][state['active_context_id']]['device'] == 'qubit' else {'blank_still_valid': blank_still_valid}
                ready = adapter._reconcile_device(view, actor_id, pending_resolution=pending_resolution, **kwargs)
                if before and pending_resolution and pending_resolution.get('outcome') == 'not_performed' and before['intent_id'] in state['bookings']:
                    resolve_not_performed(state, before['intent_id'])
                if ready is False:
                    if before and before['intent_id'] in state['bookings']: state['bookings'][before['intent_id']]['outcome'] = 'unknown'
                    state.update(status='cancelling' if cancelling else 'held',
                                 recovery_required='operation_outcome_unknown'); return
                view.local['recovery_required'] = None
            elif pending_resolution is not None: raise TaskError('No pending operation to resolve')
            state['recovery_required'] = None
            state['status'] = ('cancelling' if cancelling else 'created' if not state['rack_ready'] else
                              'running' if state['active_context_id'] else 'awaiting_choice' if state['current_sample_id'] else 'awaiting_decision')
        return self._transition('inventory_reconciled', actor_id, update,
            {'observations': observations, 'pending_resolution': pending_resolution}, allow_held=True)

    def cancel(self, actor_id, reason):
        text(reason, 'cancellation reason')
        def update(state):
            state.update(status='cancelling', cancel_requested=True,
                         recovery_required=state['recovery_required'] or 'cancel_requested')
            if state['active_context_id']:
                state['contexts'][state['active_context_id']]['local']['status'] = 'cancelling'
        return self._transition('cancel_requested', actor_id,
            update,
            {'reason': reason}, allow_held=True)

    def finish_cancel(self, actor_id, observations, workspace_clear):
        def update(state):
            if state['status'] != 'cancelling' or workspace_clear is not True: raise TaskError('Explicit cancellation and clearance required')
            self._observations(state, observations)
            if state['active_context_id']:
                context_id = state['active_context_id']
                adapter = build_adapter(self, state, context_id)
                if adapter._pending(adapter.state): raise TaskError('Resolve the pending device operation first')
                adapter.state.local['status'] = 'cancelled'
                state['active_context_id'] = None
            self._closed_inventory(state); self._audit(state)
            state.update(status='cancelled', session=None, recovery_required=None)
        return self._transition('cancel_finished', actor_id, update, {'observations': observations}, allow_held=True)

    def _audit(self, state):
        self.journal.history(self.run_id)
        for context in state['contexts'].values():
            for checksum in context['local']['imports']: self.journal.artifact(checksum)

    def report(self):
        state = self.state; self._audit(state)
        vessels = copy.deepcopy(state['inventory']['vessels'])
        for key, vessel in vessels.items():
            if vessel['kind'] in {'original', 'dilution'}:
                vessel['remaining_volume_ul'] = remaining(state, key)
                vessel['available_volume_ul'] = 0.0 if vessel['location']['kind'] == 'discarded' else vessel['remaining_volume_ul']
        return {'format': 'solidcraftbot.dna-quantification-report/1', 'run_id': self.run_id,
            'status': state['status'], 'passed': state['status'] == 'completed' and not any(s['accepted_with_flags'] for s in state['samples'].values()),
            'mode': 'synthetic_only', 'network_executed': False, 'hardware_executed': False,
            'robot_motion_executed': False, 'real_export_qualified': False, 'cross_run_volume_ledger': False,
            'logical_time_s': state['logical_time_s'], 'clock_mode': state['clock_mode'],
            'rack_on_table': state['rack_ready'], 'samples': state['samples'], 'inventory': {'vessels': vessels},
            'attempts': state['attempts'], 'contexts': state['contexts'], 'bookings': state['bookings'],
            'dilutions': state['dilutions'], 'pending_dilution': state['pending_dilution'],
            'resources': state['resources'], 'recovery_required': state['recovery_required'],
            'offered_dilutions': self._options(state), 'source_files_sha256': state['definition']['source_files_sha256'],
            'limitations': state['definition']['protocol']['limitations']}
