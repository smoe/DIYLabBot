"""Shared local manual-task lifecycle, custody and result-artifact contracts."""
import copy
import inspect
import json
import math
import re
import uuid
from pathlib import Path

import assembly_model as assembly
import furniture_model as furniture
import rack_slots
from manual_tasks import Journal, TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / 'exports/manual-workflows/nanodrop.sqlite3'
TERMINAL = {'completed', 'cancelled'}

class ObservationError(TaskError):
    """An observed discrepancy requires reconciliation, preserving reservations."""


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise TaskError('Nonempty ' + name + ' required')
    return value


def positive(value, name, zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise TaskError('Finite ' + ('nonnegative ' if zero else 'positive ') + name + ' required')
    return value


def keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise TaskError('Unexpected fields in ' + name)


def original_location(state, sample):
    return {'kind': 'rack', 'rack_id': state['definition']['profile']['rack']['id'],
            'place_id': sample['original_place_id']}


def inventory_observations(state):
    """Explicit DEMO input generator, never called by task transition validation."""
    return [{'sample_id': key, 'vessel_id': sample['vessel_id'],
             'location': copy.deepcopy(sample['location'])}
            for key, sample in state['samples'].items()] + [
                {'vessel_id': key, 'location': copy.deepcopy(vessel['location'])}
                for key, vessel in state.get('derived_vessels', {}).items()]


def compile_profile(source, profile_format, runtime_sources, extra_fields=()):
    """Bind the common spatial, instrument and manifest contracts once."""
    path = None if isinstance(source, dict) else Path(source)
    profile = copy.deepcopy(source) if path is None else json.loads(path.read_text(encoding='utf-8'))
    keys(profile, 'format id mode protocol catalog workspace instrument rack parameters samples '
         + ' '.join(extra_fields), 'profile')
    if profile['format'] != profile_format or profile['mode'] != 'synthetic_only':
        raise TaskError('Only the declared synthetic workflow profile is implemented')
    text(profile['id'], 'profile id')
    sources = {}

    def read(ref):
        keys(ref, 'source source_sha256', 'source reference')
        file = assembly.validate_reference(ref)
        sources[str(file.relative_to(ROOT))] = digest(file.read_bytes())
        return json.loads(file.read_text(encoding='utf-8'))

    protocol = read(profile['protocol'])
    if protocol['mode'] != 'synthetic_only':
        raise TaskError('Synthetic protocol required')
    if protocol['sop']['synthetic'] is not True:
        raise TaskError('Synthetic SOP required')
    for field in ['id', 'revision']:
        text(protocol['sop'][field], 'SOP ' + field)
    if set(profile['parameters']) != set(protocol['parameters']):
        raise TaskError('Unexpected parameter fields')
    for key, value in profile['parameters'].items():
        if value is None and protocol['parameters'][key].get('nullable'):
            continue
        positive(value, key)
    catalog = read(profile['catalog'])
    if catalog['format'] != 'solidcraftbot.instrument-catalog/1':
        raise TaskError('Instrument catalog required')
    instrument = profile['instrument']
    keys(instrument, 'id type serial_number software_version', 'instrument')
    for field in ['id', 'type', 'serial_number']:
        text(instrument[field], 'instrument ' + field)
    if instrument['software_version'] is not None:
        text(instrument['software_version'], 'software version')
    instrument_type = catalog['types'].get(instrument['type'])
    if not instrument_type or protocol['capability'] not in instrument_type['capabilities']:
        raise TaskError('Instrument does not provide the required capability')
    workspace = profile['workspace']
    keys(workspace, 'id environment furniture furnishings frame', 'workspace')
    text(workspace['id'], 'workspace id')
    environment = read(workspace['environment'])
    if environment['extent'] != 'unbounded' or environment['geometry'] != 'none':
        raise TaskError('Synthetic unbounded environment required')
    catalog_furniture = furniture.validate_catalog(read(workspace['furniture']))
    furnishings = read(workspace['furnishings'])
    frames = {frame['id'] for item in furnishings['instances']
              for frame in furniture.instantiate(catalog_furniture, item, {})['frames']}
    if workspace['frame'] not in frames:
        raise TaskError('Unknown reference bench frame')
    keys(profile['rack'], 'id definition', 'rack')
    text(profile['rack']['id'], 'rack instance id')
    definition = read(profile['rack']['definition'])
    if definition['format'] != 'solidcraftbot.guided-tube-rack/1':
        raise TaskError('Shared rack definition required')
    places = rack_slots.places(definition)
    samples = profile['samples']
    if not isinstance(samples, list) or not samples:
        raise TaskError('Sample manifest required')
    for sample in samples:
        keys(sample, 'id vessel_id rack_slot initial_volume_ul', 'sample')
        text(sample['id'], 'sample id')
        text(sample['vessel_id'], 'vessel id')
        if type(sample['rack_slot']) is not int or not 1 <= sample['rack_slot'] <= len(places):
            raise TaskError('Unknown rack slot')
        if sample['initial_volume_ul'] is not None:
            positive(sample['initial_volume_ul'], 'initial volume', zero=True)
    for field in ['id', 'vessel_id', 'rack_slot']:
        if len({s[field] for s in samples}) != len(samples):
            raise TaskError('Duplicate sample ' + field)
    runtime_sources = list(dict.fromkeys([
        'scripts/manual_tasks.py', 'scripts/manual_workflow.py',
        'scripts/rack_slots.py', *runtime_sources]))
    for file in runtime_sources:
        sources[file] = digest((ROOT / file).read_bytes())
    if path is not None and path.resolve().is_relative_to(ROOT):
        sources[str(path.resolve().relative_to(ROOT))] = digest(path.read_bytes())
    return {'profile': profile, 'protocol': protocol, 'instrument_type': instrument_type,
            'places': places, 'runtime_source_files': runtime_sources,
            'source_files_sha256': sources,
            'effective_profile_sha256': digest(encoded(profile).encode())}


class ManualWorkflow:
    STATE_FORMAT = None
    REPORT_FORMAT = None
    STEPS = ()
    DEADLINE_FIELD = 'deadline_unix_s'
    EVENT_CLOCK = False
    PREPLAN_MEASUREMENTS = False

    def __init__(self, journal, run_id, session):
        self.journal, self.run_id, self.session = journal, run_id, session
        self._validate_format(journal.state(run_id)[0])

    @classmethod
    def _validate_format(cls, state):
        if state.get('format') != cls.STATE_FORMAT:
            raise TaskError('Wrong workflow format; expected ' + str(cls.STATE_FORMAT))

    @classmethod
    def create(cls, journal, source=None, run_id=None):
        definition = cls.load_profile(cls.SOURCE if source is None else source)
        definition['clock_mode'] = 'synthetic_events/1' if cls.EVENT_CLOCK else journal.clock_mode
        run_id = run_id or cls.RUN_PREFIX + uuid.uuid4().hex[:12]
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise TaskError('Run id must contain 1-64 ASCII letters, digits, dots, hyphens or underscores')
        session = uuid.uuid4().hex
        state = {'format': cls.STATE_FORMAT, 'run_id': run_id, 'attempt_id': run_id + '.A01',
                 'definition': definition, 'status': 'created', 'session': session,
                 'actor_id': None, 'resources': [], 'rack_ready': False, 'workspace_clear': False,
                 'recovery_required': None, cls.DEADLINE_FIELD: None, 'samples': {},
                 'planned_measurements': {}, 'measurements': {}, 'results': {},
                 'imports': {}, 'result_review': None, **cls._initial_extra(run_id, definition)}
        for index, sample in enumerate(sorted(definition['profile']['samples'], key=lambda s: s['rack_slot']), 1):
            value = {**sample, 'original_place_id': definition['places'][sample['rack_slot'] - 1]['id'],
                     'remaining_volume_ul': sample['initial_volume_ul'], 'volume_uncertain': False,
                     'mass_confirmation_valid': False, 'return_confirmation': None}
            value['location'] = original_location(state, value)
            state['samples'][sample['id']] = value
            if cls.PREPLAN_MEASUREMENTS:
                state['planned_measurements'][sample['id']] = run_id + '.A01.M%03d' % index
        journal.create(run_id, state)
        return cls(journal, run_id, session)

    @staticmethod
    def _initial_extra(run_id, definition):
        return {}

    def _now(self, state):
        return state['logical_time_s'] if self.EVENT_CLOCK else self.journal.clock()

    def _pending(self, state):
        return state.get('pending_measurement')

    @classmethod
    def _clock_matches(cls, journal, state, clock_mode=None):
        expected = 'synthetic_events/1' if cls.EVENT_CLOCK else journal.clock_mode
        stored = state['definition'].get('clock_mode', expected)
        if stored != expected or (clock_mode is not None and clock_mode != expected):
            raise TaskError('Clock mode mismatch: ' + stored + ' versus ' + str(clock_mode or expected))

    @classmethod
    def open(cls, journal, run_id, resume=False, clock_mode=None):
        state, revision = journal.state(run_id)
        cls._validate_format(state)
        cls._clock_matches(journal, state, clock_mode)
        if state['status'] in TERMINAL:
            return cls(journal, run_id, None)
        runtime = state['definition'].get('runtime_source_files')
        if not runtime:
            raise TaskError('Runtime source manifest missing; inspect the pinned run before migration')
        for file in runtime:
            path = (ROOT / file).resolve()
            if not path.is_relative_to(ROOT) or digest(path.read_bytes()) != state['definition']['source_files_sha256'].get(file):
                raise TaskError('Runtime source changed; inspect the pinned run before migration: ' + file)
        if state['session'] and not resume:
            raise TaskError('Previous session is open; explicit resume and reconciliation required')
        session = uuid.uuid4().hex
        if state['resources'] or state['actor_id']:
            state['recovery_required'] = 'session_restarted'
            state['workspace_clear'] = False
        state['session'] = session
        journal.append(run_id, revision, 'session_opened', {'explicit_resume': resume}, state)
        return cls(journal, run_id, session)

    def close(self):
        state, revision = self.journal.state(self.run_id)
        if state['session'] == self.session and self.session is not None:
            state['session'] = None
            self.journal.append(self.run_id, revision, 'session_closed', {}, state)
        self.session = None

    @property
    def state(self):
        state = self.journal.state(self.run_id)[0]
        self._validate_format(state)
        return state

    def act(self, command, actor_id, artifact=None, **data):
        text(actor_id, 'synthetic actor id')
        state, revision = self.journal.state(self.run_id)
        self._validate_format(state)
        self._clock_matches(self.journal, state)
        if state['status'] in TERMINAL:
            raise TaskError('Run is terminal')
        if self.session is None or state['session'] != self.session:
            raise TaskError('Stale task session; reload and reconcile')
        if state['actor_id'] is not None and state['actor_id'] != actor_id:
            raise TaskError('Task is held by another synthetic actor')
        if (state[self.DEADLINE_FIELD] is not None and self._now(state) >= state[self.DEADLINE_FIELD]
                and not state['recovery_required']):
            state['recovery_required'] = 'deadline_exceeded'
            state['workspace_clear'] = False
            self.journal.append(self.run_id, revision, 'deadline_exceeded', {}, state)
            revision += 1
        allowed = set(self.STEPS) | {'take', 'reconcile', 'cancel', 'finish_cancel', 'discard_import', 'check_deadline'}
        if command not in allowed:
            raise TaskError('Unknown task command: ' + command)
        if state['recovery_required'] and command not in {'reconcile', 'cancel', 'check_deadline', 'advance_time'}:
            raise TaskError('Physical reconciliation required: ' + state['recovery_required'])
        if state['status'] == 'cancelling' and command not in {'reconcile', 'take', 'place', 'finish_cancel', 'check_deadline', 'dispose_vessel', 'advance_time'}:
            raise TaskError('Only reconciliation and return are allowed while cancelling')
        before = copy.deepcopy(state)
        payload = {**data, 'actor_id': actor_id, 'evidence': 'synthetic_input'}
        handler = getattr(self, '_' + command)
        arguments = {'artifact': artifact, **data} if command == 'import_results' else {'actor_id': actor_id, **data}
        try:
            inspect.signature(handler).bind(state, **arguments)
        except TypeError as error:
            raise TaskError('Invalid arguments for ' + command + ': ' + str(error)) from error
        try:
            changed = handler(state, **arguments)
        except ObservationError as error:
            before['recovery_required'] = 'observation_mismatch'
            before['workspace_clear'] = False
            self.journal.append(self.run_id, revision, 'observation_rejected',
                                {**payload, 'command': command, 'error': str(error)}, before)
            raise
        if changed is False:
            return state
        if artifact is not None:
            payload['artifact_sha256'] = digest(artifact)
        self.journal.append(self.run_id, revision, command, payload, state, artifact=artifact)
        return state

    @staticmethod
    def _claimed(state):
        if state['actor_id'] is None:
            raise TaskError('Claim the manual task first')

    @staticmethod
    def _require(value, message):
        if value is not True:
            raise ObservationError(message)

    @staticmethod
    def _sample(state, sample_id):
        if sample_id not in state['samples']:
            raise TaskError('Unknown sample: ' + str(sample_id))
        return state['samples'][sample_id]

    def _inventory(self, state, observations, actor_id):
        originals = {sample['vessel_id']: (key, sample) for key, sample in state['samples'].items()}
        derived = state.get('derived_vessels', {})
        expected = set(originals) | set(derived)
        if not isinstance(observations, list) or len(observations) != len(expected):
            raise ObservationError('Complete per-vessel inventory observations required')
        observed, occupied, held = {}, set(), 0
        for observation in observations:
            if not isinstance(observation, dict):
                raise ObservationError('Explicit vessel observation required')
            vessel_id = observation.get('vessel_id')
            if vessel_id not in expected or vessel_id in observed:
                raise ObservationError('Unknown, duplicate or missing observed vessel')
            if vessel_id in originals:
                keys(observation, 'sample_id vessel_id location', 'inventory observation')
                if observation['sample_id'] != originals[vessel_id][0]:
                    raise ObservationError('Observed sample/vessel identity mismatch')
            else:
                keys(observation, 'vessel_id location', 'derived vessel observation')
            location = observation['location']
            if not isinstance(location, dict):
                raise ObservationError('Explicit observed physical location required')
            kind = location.get('kind')
            if kind == 'rack' and vessel_id in originals:
                keys(location, 'kind rack_id place_id', 'rack location')
                if (location['rack_id'] != state['definition']['profile']['rack']['id']
                        or location['place_id'] not in {p['id'] for p in state['definition']['places']}):
                    raise ObservationError('Unknown observed rack instance or place')
            elif kind == 'operator':
                keys(location, 'kind actor_id', 'operator location')
                if location['actor_id'] != actor_id:
                    raise ObservationError('Observed holder disagrees with task actor')
                held += 1
            elif kind == 'logical' and vessel_id in derived:
                keys(location, 'kind holder_id place_id', 'logical vessel location')
                allowed = state['definition']['profile'].get('logical_places', [])
                if not any(location == {'kind': 'logical', **place} for place in allowed):
                    raise ObservationError('Undeclared logical vessel place')
            elif kind == 'discarded' and vessel_id in derived:
                keys(location, 'kind', 'discarded location')
            else:
                raise ObservationError('Unresolved physical location')
            key = encoded(location)
            if (kind != 'discarded' and key in occupied) or held > 1:
                raise ObservationError('Duplicate occupied place or multiple hand-held vessels')
            occupied.add(key)
            observed[vessel_id] = copy.deepcopy(location)
        return observed

    def _rack_ready(self, state, actor_id, observations):
        if state['status'] != 'created':
            raise TaskError('Rack readiness was already recorded')
        actual = self._inventory(state, observations, actor_id)
        if any(actual[s['vessel_id']] != original_location(state, s) for k, s in state['samples'].items()):
            raise ObservationError('Initial rack manifest mismatch')
        p = state['definition']['profile']
        state['resources'] = ['rack:' + p['rack']['id'], 'instrument:' + p['instrument']['id'],
                              'workspace:' + p['workspace']['id']] + [
                                  'vessel:' + sample['vessel_id'] for sample in state['samples'].values()]
        state['rack_ready'], state['status'] = True, 'ready'

    def _workspace_clear(self, state, actor_id, confirmed):
        if state['status'] != 'ready' or state['actor_id'] is not None:
            raise TaskError('Initial work-area clearance requires a ready unclaimed rack')
        self._require(confirmed, 'Synthetic work-area clearance missing')
        state['workspace_clear'] = True

    def _claim(self, state, actor_id):
        if state['status'] != 'ready' or not state['workspace_clear'] or state['actor_id']:
            raise TaskError('Ready rack and work-area clearance required before claim')
        state['actor_id'], state['status'], state['workspace_clear'] = actor_id, 'working', False
        state[self.DEADLINE_FIELD] = self._now(state) + state['definition']['profile']['parameters']['task_deadline_s']

    def _take(self, state, actor_id, sample_id, observed_sample_id, place_id, rack_id):
        self._claimed(state)
        if self._pending(state):
            raise TaskError('Resolve pending measurement first')
        sample = self._sample(state, sample_id)
        expected = {'kind': 'rack', 'rack_id': rack_id, 'place_id': place_id}
        if sample['location'] != expected or observed_sample_id != sample_id:
            raise ObservationError('Pickup identity or source place mismatch')
        vessels = [*state['samples'].values(), *state.get('derived_vessels', {}).values()]
        if any(vessel['location']['kind'] == 'operator' for vessel in vessels):
            raise TaskError('Place the held vessel before another pickup')
        sample['location'] = {'kind': 'operator', 'actor_id': actor_id}
        sample['return_confirmation'] = None

    def _place(self, state, actor_id, sample_id, observed_sample_id, place_id, rack_id):
        self._claimed(state)
        sample = self._sample(state, sample_id)
        target = {'kind': 'rack', 'rack_id': rack_id, 'place_id': place_id}
        if self._pending(state):
            raise TaskError('Resolve pending measurement before returning the vessel')
        if (observed_sample_id != sample_id or target != original_location(state, sample)
                or sample['location'] != {'kind': 'operator', 'actor_id': actor_id}):
            raise ObservationError('Return identity, holder or original rack place mismatch')
        if any(s['location'] == target for s in state['samples'].values()):
            raise ObservationError('Original rack place is occupied')
        sample['location'] = target
        sample['return_confirmation'] = {'actor_id': actor_id, 'evidence': 'synthetic_input',
                                          'place_id': place_id, 'rack_id': rack_id}

    def import_file(self, path, actor_id, origin='synthetic_export'):
        path = Path(path)
        return self.act('import_results', actor_id, artifact=path.read_bytes(),
                        file_name=path.name, origin=origin)

    def _check_withdrawal(self, state, sample_id):
        sample = self._sample(state, sample_id)
        planned = state['definition']['profile']['parameters']['sample_volume_ul']
        if sample['remaining_volume_ul'] is not None and sample['remaining_volume_ul'] < planned:
            raise TaskError('Insufficient recorded volume for the planned withdrawal')

    def _consume(self, state, sample_id, volume_ul, deviation_reason=None):
        positive(volume_ul, 'withdrawn volume in uL')
        planned = state['definition']['profile']['parameters']['sample_volume_ul']
        if not math.isclose(volume_ul, planned, rel_tol=0, abs_tol=1e-9):
            text(deviation_reason, 'reason for volume deviation')
        sample = self._sample(state, sample_id)
        remaining = sample['remaining_volume_ul']
        if remaining is not None:
            if volume_ul > remaining:
                raise ObservationError('Withdrawal exceeds recorded remaining volume')
            sample['remaining_volume_ul'] = remaining - volume_ul
        sample['volume_uncertain'], sample['mass_confirmation_valid'] = False, False

    def _import_results(self, state, artifact, file_name, origin='synthetic_export'):
        self._claimed(state)
        text(file_name, 'artifact file name')
        if origin not in {'synthetic_export', 'synthetic_manual_entry'}:
            raise TaskError('Only explicitly synthetic result origins are supported')
        self._before_import(state)
        if not isinstance(artifact, bytes):
            raise TaskError('Original report bytes required')
        checksum = digest(artifact)
        if checksum in state['imports']:
            return False
        try:
            report, issues, results = self._parse_import(state, artifact, origin)
        except TaskError as error:
            report, issues, results = None, [str(error)], {}
        if state['results']:
            issues.append('conflicting_result_import')
        state['imports'][checksum] = {
            'file_name': Path(file_name).name, 'sha256': checksum, 'byte_count': len(artifact),
            'origin': origin, 'status': 'quarantined' if issues else 'accepted',
            'issues': issues, 'report': report}
        if not issues:
            state['results'] = results
        state['result_review'] = None

    def _expected_results(self, state):
        return set(state['planned_measurements'].values())

    def _scientific_ready(self, state):
        pass

    def _reconcile(self, state, actor_id, observations, workspace_clear, **device_data):
        if not state['recovery_required']:
            raise TaskError('No physical reconciliation is pending')
        if type(workspace_clear) is not bool:
            raise TaskError('Explicit workspace observation required')
        try:
            inspect.signature(self._reconcile_device).bind(state, actor_id, **device_data)
        except TypeError as error:
            raise TaskError('Invalid reconciliation arguments: ' + str(error)) from error
        locations = self._inventory(state, observations, actor_id)
        for sample in state['samples'].values():
            sample['location'] = locations[sample['vessel_id']]
            sample['return_confirmation'] = (
                {'actor_id': actor_id, 'evidence': 'synthetic_input', **sample['location']}
                if sample['location'] == original_location(state, sample) else None)
        for vessel_id, vessel in state.get('derived_vessels', {}).items():
            vessel['location'] = locations[vessel_id]
            vessel['disposition_confirmation'] = (
                {'actor_id': actor_id, 'evidence': 'synthetic_input'}
                if vessel['location']['kind'] == 'discarded' else None)
        if self._reconcile_device(state, actor_id, **device_data) is False:
            return
        state['recovery_required'] = None
        state['workspace_clear'] = workspace_clear
        if state['actor_id']:
            state[self.DEADLINE_FIELD] = self._now(state) + state['definition']['profile']['parameters']['task_deadline_s']

    def _dispose_vessel(self, state, actor_id, vessel_id, observed_vessel_id, reason):
        self._claimed(state)
        text(reason, 'disposal reason')
        if self._pending(state):
            raise TaskError('Resolve pending operation before disposal')
        vessel = state.get('derived_vessels', {}).get(vessel_id)
        if not vessel or vessel_id != observed_vessel_id:
            raise ObservationError('Derived vessel disposal identity mismatch')
        if vessel['location']['kind'] == 'discarded':
            raise TaskError('Vessel was already discarded')
        vessel['location'] = {'kind': 'discarded'}
        vessel['disposition_confirmation'] = {'actor_id': actor_id, 'reason': reason,
                                             'evidence': 'synthetic_input'}

    def _advance_time(self, state, actor_id, seconds):
        if not self.EVENT_CLOCK:
            raise TaskError('Only event-clock workflows can advance synthetic time')
        positive(seconds, 'synthetic elapsed seconds')
        following = state['logical_time_s'] + seconds
        positive(following, 'resulting synthetic time')
        state['logical_time_s'] = following
        if state[self.DEADLINE_FIELD] is not None and self._now(state) >= state[self.DEADLINE_FIELD]:
            state['recovery_required'] = 'deadline_exceeded'
            state['workspace_clear'] = False

    def _discard_import(self, state, actor_id, sha256, reason):
        self._claimed(state)
        text(reason, 'discard reason')
        record = state['imports'].get(sha256)
        if not record or record['status'] != 'quarantined':
            raise TaskError('Only a quarantined import can be discarded')
        record.update(status='discarded', discard_reason=reason, discarded_by=actor_id)

    def _review_results(self, state, actor_id, decision, reason):
        self._claimed(state)
        text(reason, 'review reason')
        if decision not in {'accepted', 'rejected'}:
            raise TaskError('Explicit accepted/rejected decision required')
        if set(state['results']) != self._expected_results(state):
            raise TaskError('Complete matched results required')
        if any(record['status'] == 'quarantined' for record in state['imports'].values()):
            raise TaskError('Resolve quarantined imports first')
        self._verify_artifacts(state)
        self._scientific_ready(state)
        state['result_review'] = {'decision': decision, 'reason': reason,
                                   'actor_id': actor_id, 'evidence': 'synthetic_input'}

    def _restored(self, state):
        if self._pending(state) or any(
                sample['location'] != original_location(state, sample) or not sample['return_confirmation']
                for sample in state['samples'].values()):
            raise TaskError('Confirmed return to every original rack place required')
        if any(vessel['location']['kind'] != 'discarded' or not vessel['disposition_confirmation']
               for vessel in state.get('derived_vessels', {}).values()):
            raise TaskError('Confirmed disposal of every derived vessel required')

    def _release(self, state, actor_id, workspace_clear):
        self._claimed(state)
        self._require(workspace_clear, 'Final work-area handback confirmation missing')
        self._restored(state)
        if not state['result_review'] or state['result_review']['decision'] != 'accepted':
            raise TaskError('Accepted result review required before workflow continuation')
        if any(record['status'] == 'quarantined' for record in state['imports'].values()):
            raise TaskError('Quarantined imports block completion')
        self._verify_artifacts(state)
        self._scientific_ready(state)
        state.update(status='completed', workspace_clear=True, resources=[], session=None)

    def _cancel(self, state, actor_id, reason):
        text(reason, 'cancellation reason')
        state['cancel_reason'] = reason
        if state['resources']:
            state['status'], state['recovery_required'] = 'cancelling', 'cancel_inventory_check'
            state['workspace_clear'] = False
        else:
            state.update(status='cancelled', session=None)

    def _finish_cancel(self, state, actor_id, workspace_clear):
        if state['status'] != 'cancelling':
            raise TaskError('No cancellation pending')
        self._require(workspace_clear, 'Cancellation handback clearance missing')
        self._restored(state)
        state.update(status='cancelled', workspace_clear=True, resources=[], session=None)

    @staticmethod
    def _check_deadline(state, actor_id):
        return False

    def _verify_artifacts(self, state):
        for checksum, record in state['imports'].items():
            if len(self.journal.artifact(checksum)) != record['byte_count']:
                raise TaskError('Artifact size mismatch: ' + checksum)

    def report(self):
        state = self.state
        self._verify_artifacts(state)
        restored = all(s['location'] == original_location(state, s) and s['return_confirmation']
                       for s in state['samples'].values()) and self._pending(state) is None
        samples = copy.deepcopy(state['samples'])
        for sample in samples.values():
            sample['initial_volume_source'] = 'profile_declaration; no cross-run volume ledger'
            if sample['volume_uncertain']:
                sample['remaining_volume_ul'] = None
        return {'format': self.REPORT_FORMAT,
                'run_id': self.run_id, 'attempt_id': state['attempt_id'], 'mode': 'synthetic_only',
                'passed': state['status'] == 'completed', 'status': state['status'],
                'order_restored': bool(restored), 'recovery_required': state['recovery_required'],
                'resources': state['resources'], 'samples': samples,
                'measurements': state['measurements'], 'results': state['results'],
                'imports': state['imports'], 'result_review': state['result_review'],
                'source_files_sha256': state['definition']['source_files_sha256'],
                'effective_profile_sha256': state['definition']['effective_profile_sha256'],
                'network_executed': False, 'hardware_executed': False,
                'robot_motion_executed': False, 'safety_function_qualified': False,
                'real_export_validated': False, 'cf01_continuation_executed': False,
                'evidence': 'synthetic human inputs and synthetic report files',
                'limitations': state['definition']['protocol']['limitations'],
                'trace': self.journal.history(self.run_id)}
