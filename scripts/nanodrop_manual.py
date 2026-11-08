"""Synthetic, resumable Rack -> human NanoDrop task -> original rack places.

There is no NanoDrop, robot, network, Qubit or CF01 execution in this module.
Every physical observation is a caller-supplied synthetic input, not a sensor.
"""
import copy
import json
import math
import re
import uuid
from pathlib import Path

import assembly_model as assembly
import furniture_model as furniture
import rack_slots
from manual_tasks import Journal, TaskError, digest, encoded
from nanodrop_csv import parse_report

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/nanodrop-manual.synthetic.json'
TERMINAL = {'completed', 'cancelled'}
STEPS = ['rack_ready', 'workspace_clear', 'claim', 'blank', 'begin_measurement',
         'confirm_measurement', 'place', 'import_results', 'review_results', 'release']


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


def load_profile(source=SOURCE):
    """Compile pinned sources and semantic bindings without a CAD dependency."""
    path = None if isinstance(source, dict) else Path(source)
    profile = copy.deepcopy(source) if path is None else json.loads(path.read_text(encoding='utf-8'))
    keys(profile, 'format id mode protocol catalog workspace instrument rack parameters samples', 'profile')
    if (profile['format'] != 'solidcraftbot.nanodrop-manual-profile/1'
            or profile['mode'] != 'synthetic_only'):
        raise TaskError('Only the synthetic NanoDrop profile is implemented')
    text(profile['id'], 'profile id')
    sources = {}

    def read(ref):
        keys(ref, 'source source_sha256', 'source reference')
        file = assembly.validate_reference(ref)
        sources[str(file.relative_to(ROOT))] = digest(file.read_bytes())
        return json.loads(file.read_text(encoding='utf-8'))

    protocol = read(profile['protocol'])
    if (protocol['format'] != 'solidcraftbot.nanodrop-manual-protocol/1'
            or protocol['mode'] != 'synthetic_only' or protocol['method'] != 'dsDNA'
            or protocol['capability'] != 'microvolume_absorbance'
            or protocol['steps'] != STEPS or protocol['return_policy'] != 'original_place'
            or protocol['sop']['synthetic'] is not True):
        raise TaskError('Unsupported NanoDrop protocol contract')
    if protocol['parameters'] != {
            'sample_volume_ul': {'unit': 'uL', 'exclusive_minimum': 0},
            'task_deadline_s': {'unit': 's', 'exclusive_minimum': 0}}:
        raise TaskError('Unsupported parameter contract')
    for field in ['id', 'revision']:
        text(protocol['sop'][field], 'SOP ' + field)
    keys(profile['parameters'], 'sample_volume_ul task_deadline_s', 'parameters')
    for key, value in profile['parameters'].items():
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
    if instrument_type['identity_column'] != 'Sample Name':
        raise TaskError('Unsupported report identity column')
    workspace = profile['workspace']
    keys(workspace, 'id environment furniture furnishings frame', 'workspace')
    text(workspace['id'], 'workspace id')
    environment = read(workspace['environment'])
    if environment['extent'] != 'unbounded' or environment['geometry'] != 'none':
        raise TaskError('Synthetic unbounded environment required')
    furniture_catalog = furniture.validate_catalog(read(workspace['furniture']))
    furnishing = read(workspace['furnishings'])
    frames = set()
    for item in furnishing['instances']:
        frames.update(frame['id'] for frame in furniture.instantiate(furniture_catalog, item, {})['frames'])
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
    for file in ['scripts/manual_tasks.py', 'scripts/nanodrop_manual.py',
                 'scripts/nanodrop_csv.py', 'scripts/run_nanodrop_manual.py', 'scripts/rack_slots.py',
                 'model/nanodrop-manual.schema.json']:
        sources[file] = digest((ROOT / file).read_bytes())
    if path is not None and path.resolve().is_relative_to(ROOT):
        sources[str(path.resolve().relative_to(ROOT))] = digest(path.read_bytes())
    return {'profile': profile, 'protocol': protocol, 'instrument_type': instrument_type,
            'places': places, 'source_files_sha256': sources,
            'effective_profile_sha256': digest(encoded(profile).encode())}


def original_location(state, sample):
    return {'kind': 'rack', 'rack_id': state['definition']['profile']['rack']['id'],
            'place_id': sample['original_place_id']}


def inventory_observations(state):
    """Explicit DEMO input generator, never called by task transition validation."""
    return [{'sample_id': key, 'vessel_id': sample['vessel_id'],
             'location': copy.deepcopy(sample['location'])}
            for key, sample in state['samples'].items()]


class Workflow:
    def __init__(self, journal, run_id, session):
        self.journal, self.run_id, self.session = journal, run_id, session

    @classmethod
    def create(cls, journal, source=SOURCE, run_id=None):
        definition = load_profile(source)
        run_id = run_id or 'SYN-ND-' + uuid.uuid4().hex[:12]
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise TaskError('Run id must contain 1-64 ASCII letters, digits, dots, hyphens or underscores')
        session = uuid.uuid4().hex
        state = {'format': 'solidcraftbot.nanodrop-manual-state/1', 'run_id': run_id,
                 'attempt_id': run_id + '.A01', 'definition': definition,
                 'status': 'created', 'session': session, 'actor_id': None,
                 'resources': [], 'rack_ready': False, 'workspace_clear': False,
                 'recovery_required': None, 'deadline_unix_s': None,
                 'samples': {}, 'planned_measurements': {}, 'blanks': {},
                 'active_blank': None, 'pending_measurement': None,
                 'measurements': {}, 'results': {}, 'imports': {}, 'result_review': None}
        for index, sample in enumerate(sorted(definition['profile']['samples'], key=lambda s: s['rack_slot']), 1):
            value = {**sample, 'original_place_id': definition['places'][sample['rack_slot'] - 1]['id'],
                     'remaining_volume_ul': sample['initial_volume_ul'], 'volume_uncertain': False,
                     'mass_confirmation_valid': False, 'return_confirmation': None}
            value['location'] = original_location(state, value)
            state['samples'][sample['id']] = value
            state['planned_measurements'][sample['id']] = run_id + '.A01.M%03d' % index
        journal.create(run_id, state)
        return cls(journal, run_id, session)

    @classmethod
    def open(cls, journal, run_id, resume=False):
        state, revision = journal.state(run_id)
        if state['status'] in TERMINAL:
            return cls(journal, run_id, None)
        for file in ['scripts/manual_tasks.py', 'scripts/nanodrop_manual.py', 'scripts/nanodrop_csv.py']:
            if digest((ROOT / file).read_bytes()) != state['definition']['source_files_sha256'][file]:
                raise TaskError('Runtime source changed; inspect the pinned run before migration: ' + file)
        if state['session'] and not resume:
            raise TaskError('Previous session is open; explicit resume and reconciliation required')
        session = uuid.uuid4().hex
        if state['resources'] or state['actor_id'] or state['pending_measurement']:
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
        return self.journal.state(self.run_id)[0]

    def act(self, command, actor_id, artifact=None, **data):
        text(actor_id, 'synthetic actor id')
        state, revision = self.journal.state(self.run_id)
        if state['status'] in TERMINAL:
            raise TaskError('Run is terminal')
        if self.session is None or state['session'] != self.session:
            raise TaskError('Stale task session; reload and reconcile')
        if state['actor_id'] is not None and state['actor_id'] != actor_id:
            raise TaskError('Task is held by another synthetic actor')
        if (state['deadline_unix_s'] is not None and self.journal.clock() >= state['deadline_unix_s']
                and not state['recovery_required']):
            state['recovery_required'] = 'deadline_exceeded'
            state['workspace_clear'] = False
            self.journal.append(self.run_id, revision, 'deadline_exceeded', {}, state)
            revision += 1
        allowed = set(STEPS) | {'take', 'reconcile', 'cancel', 'finish_cancel', 'discard_import', 'check_deadline'}
        if command not in allowed:
            raise TaskError('Unknown task command: ' + command)
        if state['recovery_required'] and command not in {'reconcile', 'cancel', 'check_deadline'}:
            raise TaskError('Physical reconciliation required: ' + state['recovery_required'])
        if state['status'] == 'cancelling' and command not in {'reconcile', 'take', 'place', 'finish_cancel', 'check_deadline'}:
            raise TaskError('Only reconciliation and return are allowed while cancelling')
        before = copy.deepcopy(state)
        payload = {**data, 'actor_id': actor_id, 'evidence': 'synthetic_input'}
        try:
            if command == 'import_results':
                changed = self._import_results(state, artifact=artifact, **data)
            else:
                changed = getattr(self, '_' + command)(state, actor_id=actor_id, **data)
        except ObservationError as error:
            before['recovery_required'] = 'observation_mismatch'
            before['workspace_clear'] = False
            self.journal.append(self.run_id, revision, 'observation_rejected',
                                {**payload, 'command': command, 'error': str(error)}, before)
            raise
        except TypeError as error:
            raise TaskError('Invalid arguments for ' + command + ': ' + str(error)) from error
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
        if not isinstance(observations, list) or len(observations) != len(state['samples']):
            raise ObservationError('Complete per-vessel inventory observations required')
        observed, occupied, held = {}, set(), 0
        for observation in observations:
            keys(observation, 'sample_id vessel_id location', 'inventory observation')
            sample_id = observation['sample_id']
            if sample_id not in state['samples'] or sample_id in observed:
                raise ObservationError('Unknown, duplicate or missing observed sample')
            sample = state['samples'][sample_id]
            if observation['vessel_id'] != sample['vessel_id']:
                raise ObservationError('Observed vessel identity mismatch: ' + sample_id)
            location = observation['location']
            if not isinstance(location, dict):
                raise ObservationError('Explicit observed physical location required')
            if location.get('kind') == 'rack':
                keys(location, 'kind rack_id place_id', 'rack location')
                if (location['rack_id'] != state['definition']['profile']['rack']['id']
                        or location['place_id'] not in {p['id'] for p in state['definition']['places']}):
                    raise ObservationError('Unknown observed rack instance or place')
            elif location.get('kind') == 'operator':
                keys(location, 'kind actor_id', 'operator location')
                if location['actor_id'] != actor_id:
                    raise ObservationError('Observed holder disagrees with task actor')
                held += 1
            else:
                raise ObservationError('Unresolved physical location')
            key = encoded(location)
            if key in occupied or held > 1:
                raise ObservationError('Duplicate occupied place or multiple hand-held vessels')
            occupied.add(key)
            observed[sample_id] = copy.deepcopy(location)
        return observed

    def _rack_ready(self, state, actor_id, observations):
        if state['status'] != 'created':
            raise TaskError('Rack readiness was already recorded')
        actual = self._inventory(state, observations, actor_id)
        if any(actual[k] != original_location(state, s) for k, s in state['samples'].items()):
            raise ObservationError('Initial rack manifest mismatch')
        p = state['definition']['profile']
        state['resources'] = ['rack:' + p['rack']['id'], 'instrument:' + p['instrument']['id'],
                              'workspace:' + p['workspace']['id']]
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
        state['deadline_unix_s'] = self.journal.clock() + state['definition']['profile']['parameters']['task_deadline_s']

    def _blank(self, state, actor_id, reference_id, cleaned):
        self._claimed(state)
        if state['pending_measurement']:
            raise TaskError('Resolve pending measurement before a new blank')
        text(reference_id, 'synthetic blank reference')
        self._require(cleaned, 'Blank cleanup confirmation missing')
        blank_id = state['run_id'] + '.A01.B%03d' % (len(state['blanks']) + 1)
        state['blanks'][blank_id] = {'reference_id': reference_id,
                                     'actor_id': actor_id, 'evidence': 'synthetic_input'}
        state['active_blank'] = blank_id

    def _take(self, state, actor_id, sample_id, observed_sample_id, place_id, rack_id):
        self._claimed(state)
        if state['pending_measurement']:
            raise TaskError('Resolve pending measurement first')
        sample = self._sample(state, sample_id)
        expected = {'kind': 'rack', 'rack_id': rack_id, 'place_id': place_id}
        if sample['location'] != expected or observed_sample_id != sample_id:
            raise ObservationError('Pickup identity or source place mismatch')
        if any(s['location']['kind'] == 'operator' for s in state['samples'].values()):
            raise TaskError('Place the held vessel before another pickup')
        sample['location'] = {'kind': 'operator', 'actor_id': actor_id}
        sample['return_confirmation'] = None

    def _begin_measurement(self, state, actor_id, sample_id, measurement_id):
        self._claimed(state)
        sample = self._sample(state, sample_id)
        if (state['pending_measurement'] or not state['active_blank']
                or sample['location'] != {'kind': 'operator', 'actor_id': actor_id}):
            raise TaskError('Blank, held original vessel and no pending measurement required')
        if measurement_id != state['planned_measurements'][sample_id] or measurement_id in state['measurements']:
            raise TaskError('Unexpected or already completed measurement id')
        planned = state['definition']['profile']['parameters']['sample_volume_ul']
        if sample['remaining_volume_ul'] is not None and sample['remaining_volume_ul'] < planned:
            raise TaskError('Insufficient recorded volume for the planned withdrawal')
        state['pending_measurement'] = {'intent_id': uuid.uuid4().hex, 'sample_id': sample_id,
                                        'measurement_id': measurement_id,
                                        'blank_id': state['active_blank']}
        sample['volume_uncertain'] = True

    def _finish_measurement(self, state, intent_id, observed_sample_id, volume_ul, cleaned,
                            deviation_reason=None):
        pending = state['pending_measurement']
        if not pending or pending['intent_id'] != intent_id:
            raise TaskError('Stale or unknown measurement intent')
        if observed_sample_id != pending['sample_id']:
            raise ObservationError('Measurement sample identity mismatch')
        self._require(cleaned, 'Measurement cleanup confirmation missing')
        positive(volume_ul, 'withdrawn volume in uL')
        planned = state['definition']['profile']['parameters']['sample_volume_ul']
        if not math.isclose(volume_ul, planned, rel_tol=0, abs_tol=1e-9):
            text(deviation_reason, 'reason for volume deviation')
        sample = state['samples'][pending['sample_id']]
        remaining = sample['remaining_volume_ul']
        if remaining is not None:
            if volume_ul > remaining:
                raise ObservationError('Withdrawal exceeds recorded remaining volume')
            sample['remaining_volume_ul'] = remaining - volume_ul
        sample['volume_uncertain'], sample['mass_confirmation_valid'] = False, False
        measurement_id = pending['measurement_id']
        state['measurements'][measurement_id] = {
            **pending, 'parent_sample_id': pending['sample_id'],
            'source_vessel_id': sample['vessel_id'], 'aliquot_id': measurement_id + '.Aliquot',
            'withdrawn_volume': {'value': volume_ul, 'unit': 'uL'},
            'disposition': 'discarded_after_synthetic_cleanup',
            'sop': state['definition']['protocol']['sop'], 'deviation_reason': deviation_reason,
            'actor_id': state['actor_id'], 'evidence': 'synthetic_input'}
        state['pending_measurement'] = None

    def _confirm_measurement(self, state, actor_id, **data):
        self._claimed(state)
        self._finish_measurement(state, **data)

    def _place(self, state, actor_id, sample_id, observed_sample_id, place_id, rack_id):
        self._claimed(state)
        sample = self._sample(state, sample_id)
        target = {'kind': 'rack', 'rack_id': rack_id, 'place_id': place_id}
        if state['pending_measurement']:
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

    def _import_results(self, state, artifact, file_name, origin='synthetic_export'):
        self._claimed(state)
        text(file_name, 'artifact file name')
        if origin not in {'synthetic_export', 'synthetic_manual_entry'}:
            raise TaskError('Only explicitly synthetic result origins are supported')
        if state['pending_measurement'] or set(state['measurements']) != set(state['planned_measurements'].values()):
            raise TaskError('Confirm all planned measurements before importing the batch')
        if not isinstance(artifact, bytes):
            raise TaskError('Original report bytes required')
        checksum = digest(artifact)
        if checksum in state['imports']:
            return False
        issues, report = [], None
        try:
            report = parse_report(artifact, state['definition']['instrument_type']['identity_column'])
            expected = set(state['planned_measurements'].values())
            names = [row['measurement_id'] for row in report['rows']]
            sample_names = [name for name in names if name not in state['blanks']]
            if len(set(names)) != len(names):
                issues.append('duplicate_measurement')
            if set(sample_names) - expected:
                issues.append('foreign_measurement')
            if expected - set(sample_names):
                issues.append('missing_measurement')
            metadata = report['metadata']
            if metadata.get('application', state['definition']['protocol']['method']) != state['definition']['protocol']['method']:
                issues.append('method_mismatch')
            serial = state['definition']['profile']['instrument']['serial_number']
            if metadata.get('serialnumber', serial) != serial:
                issues.append('instrument_serial_mismatch')
            for row in report['rows']:
                if row['metadata'].get('application', state['definition']['protocol']['method']) != state['definition']['protocol']['method']:
                    issues.append('method_mismatch')
                if row['metadata'].get('serialnumber', serial) != serial:
                    issues.append('instrument_serial_mismatch')
            if state['results']:
                issues.append('conflicting_result_import')
        except TaskError as error:
            issues.append(str(error))
        state['imports'][checksum] = {
            'file_name': Path(file_name).name, 'sha256': checksum, 'byte_count': len(artifact),
            'origin': origin, 'status': 'quarantined' if issues else 'accepted',
            'issues': issues, 'report': report}
        if not issues:
            for row in report['rows']:
                if row['measurement_id'] in state['blanks']:
                    continue
                measurement = state['measurements'][row['measurement_id']]
                state['results'][row['measurement_id']] = {
                    **row, 'sample_id': measurement['sample_id'], 'aliquot_id': measurement['aliquot_id'],
                    'blank_id': measurement['blank_id'], 'artifact_sha256': checksum,
                    'origin': origin, 'method': state['definition']['protocol']['method'],
                    'method_source': 'report' if 'application' in report['metadata'] or 'application' in row['metadata'] else 'profile_declaration',
                    'instrument': state['definition']['profile']['instrument'],
                    'serial_source': 'report' if 'serialnumber' in report['metadata'] or 'serialnumber' in row['metadata'] else 'profile_declaration',
                    'concentration_basis': 'reported; no additional dilution or purity correction applied'}
        state['result_review'] = None

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
        if set(state['results']) != set(state['planned_measurements'].values()):
            raise TaskError('Complete matched results required')
        if any(record['status'] == 'quarantined' for record in state['imports'].values()):
            raise TaskError('Resolve quarantined imports first')
        self._verify_artifacts(state)
        state['result_review'] = {'decision': decision, 'reason': reason,
                                   'actor_id': actor_id, 'evidence': 'synthetic_input'}

    def _reconcile(self, state, actor_id, observations, workspace_clear,
                   blank_still_valid, pending_resolution=None):
        if not state['recovery_required']:
            raise TaskError('No physical reconciliation is pending')
        if type(workspace_clear) is not bool or type(blank_still_valid) is not bool:
            raise TaskError('Explicit workspace and blank observations required')
        locations = self._inventory(state, observations, actor_id)
        for key, location in locations.items():
            sample = state['samples'][key]
            sample['location'] = location
            sample['return_confirmation'] = (
                {'actor_id': actor_id, 'evidence': 'synthetic_input', **location}
                if location == original_location(state, sample) else None)
        pending = state['pending_measurement']
        if pending:
            if not isinstance(pending_resolution, dict):
                raise TaskError('Explicit pending measurement outcome required')
            outcome = pending_resolution.get('outcome')
            if pending_resolution.get('intent_id') != pending['intent_id']:
                raise TaskError('Pending measurement intent mismatch')
            if outcome == 'unknown':
                state['samples'][pending['sample_id']]['volume_uncertain'] = True
                state['recovery_required'] = 'measurement_outcome_unknown'
                return
            if outcome == 'performed':
                self._finish_measurement(state, **{k: v for k, v in pending_resolution.items() if k != 'outcome'})
            elif outcome == 'not_performed':
                keys(pending_resolution, 'intent_id outcome', 'pending measurement resolution')
                state['samples'][pending['sample_id']]['volume_uncertain'] = False
                state['pending_measurement'] = None
            else:
                raise TaskError('Unknown pending measurement outcome')
        elif pending_resolution is not None:
            raise TaskError('No measurement intent to resolve')
        state['recovery_required'] = None
        state['workspace_clear'] = workspace_clear
        if not blank_still_valid:
            state['active_blank'] = None
        if state['actor_id']:
            state['deadline_unix_s'] = self.journal.clock() + state['definition']['profile']['parameters']['task_deadline_s']

    def _restored(self, state):
        if state['pending_measurement'] or any(
                sample['location'] != original_location(state, sample) or not sample['return_confirmation']
                for sample in state['samples'].values()):
            raise TaskError('Confirmed return to every original rack place required')

    def _release(self, state, actor_id, workspace_clear):
        self._claimed(state)
        self._require(workspace_clear, 'Final work-area handback confirmation missing')
        self._restored(state)
        if not state['result_review'] or state['result_review']['decision'] != 'accepted':
            raise TaskError('Accepted result review required before workflow continuation')
        if any(record['status'] == 'quarantined' for record in state['imports'].values()):
            raise TaskError('Quarantined imports block completion')
        self._verify_artifacts(state)
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
                       for s in state['samples'].values()) and state['pending_measurement'] is None
        samples = copy.deepcopy(state['samples'])
        for sample in samples.values():
            if sample['volume_uncertain']:
                sample['remaining_volume_ul'] = None
        return {'format': 'solidcraftbot.nanodrop-manual-report/1',
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
