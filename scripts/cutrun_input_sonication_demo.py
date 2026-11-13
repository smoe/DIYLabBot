"""Explicit software fixtures for the existing Root journal; no lab operations.

The committed fixture file is the single source of invented demo values. The
manufacturer original stays missing and the real SOP readiness stays false.
"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

import cutrun_input_sonication_sources as sources
from cutrun_input_sonication_workflow import InputSonicationWorkflow
import cutrun_manual_sources as manual_sources
import dna_sonication
import material_ledger as ledger
import manual_process_clock
from manual_tasks import TaskError, digest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'model/cutrun-input-sonication.fixture.json'


def fixture_values():
    data = json.loads(FIXTURE.read_bytes())
    if data.get('format') != 'solidcraftbot.cutrun-input-sonication-fixture/1' or data.get('mode') != 'test_fixture_only':
        raise TaskError('Explicit test-only sonication fixture required')
    return data


def validate_run_id(run_id):
    if (not isinstance(run_id, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id) is None
            or run_id.startswith('SYN.')):
        raise TaskError('Run id requires 1-64 ASCII letters, digits, dots, underscores or hyphens; no path separators or SYN. prefix')
    return run_id


class FixtureClock:
    """Declared test-clock observations, never a calibrated process timer."""
    def __init__(self, *, clock_id='Fixture.Clock', process_id='Fixture.Writer', record=None):
        self.record = copy.deepcopy(record) if record is not None else {
            'format': manual_process_clock.FORMAT, 'source_kind': 'test_clock',
            'clock_id': clock_id, 'process_id': process_id, 'utc': fixture_values()['utc_start'],
            'monotonic_ns': 0, 'uncertainty_s': 0, 'suspend_policy': 'inclusive'}

    def sample(self):
        return copy.deepcopy(self.record)

    def advance(self, seconds):
        if type(seconds) not in (int, float) or seconds < 0:
            raise TaskError('Nonnegative fixture seconds required')
        self.record['monotonic_ns'] += round(seconds * 1_000_000_000)
        stamp = datetime.fromisoformat(self.record['utc'].replace('Z', '+00:00'))
        self.record['utc'] = (stamp + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')


class FixtureSession:
    """Build one independent fixture; never reset or rename a real inventory."""
    def __init__(self, journal, run_id, directory, scenario_id='normal', *,
                 workflow_class=InputSonicationWorkflow, workflow_options=None,
                 reuse_fixture_evidence=False, initialize_fixture=True):
        validate_run_id(run_id)
        self.journal, self.run_id = journal, run_id
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fixture = fixture_values()
        scenario = self.fixture['scenarios'][scenario_id]
        self.prefix = scenario['prefix']
        self.actor = self.fixture['actor_id']
        self.reaction_id = self.prefix + '.Reaction.Input'
        self.vessel_id = self.prefix + '.input.Tube'
        self.origin_location = {'kind': 'rack', 'rack_id': self.prefix + '.Rack', 'place_id': 'P07'}
        self.stage_run_id = self.prefix + '.Stage.S09'
        self.intent_id = self.prefix + '.Sonication'
        self.output_material_id = self.prefix + '.FragmentedInput'
        self.device_id = self.prefix + '.Sonicator'
        self.clock = FixtureClock(clock_id=scenario['clock_id'], process_id=self.prefix + '.Writer.1')
        self.time_basis = self.clock.record['clock_id']
        self.serial = 0
        self._started_ns = time.perf_counter_ns()
        self._samples = []
        self._last_sequence = 0
        self.phase_started_s = 0.0
        evidence = self.directory / (run_id + '.fixture-decisions.json')
        content = FIXTURE.read_bytes()
        if reuse_fixture_evidence and evidence.exists():
            if evidence.read_bytes() != content:
                raise TaskError('Existing fixture evidence differs; never replace an original')
        else:
            with evidence.open('xb') as stream:
                stream.write(content)
        self.evidence_files = {'decision_evidence': evidence}
        self.materials, self.vessels, self.reactions = self._declarations()
        self.source = self._source()
        self.flow = workflow_class.create(journal, self.source,
            materials=self.materials, vessels=self.vessels, reactions=self.reactions,
            actors=[self.actor], run_id=run_id, clock=self.clock,
            original_pdf=None, evidence_files=self.evidence_files,
            **(workflow_options or {}))
        self.capture()
        if initialize_fixture:
            self.act('accept_inventory', observations=self.flow.inventory_observations())
            self.act('workspace_clear', confirmed=True)
            self.act('claim')

    def _declarations(self):
        materials, reactions = [], {}
        for role in ('h3k4me3', 'igg', 'input'):
            material = self.prefix + '.' + role
            vessel = material + '.Tube'
            materials.append({'id': material, 'kind': 'sample' if role == 'h3k4me3' else 'control',
                'vessel_id': vessel, 'quantity': {'value': self.fixture['initial_cells'], 'unit': 'cells'},
                'origin_id': self.prefix + '.Culture'})
            reagents = {}
            for operation in (() if role == 'input' else ('activation', 'stop')):
                identity = material + '.' + operation
                materials.append({'id': identity, 'kind': 'reagent', 'vessel_id': identity + '.Tube',
                    'quantity': {'value': self.fixture['issued_reagent_ul'], 'unit': 'uL'},
                    'origin_id': self.prefix + '.Issued.' + operation})
                reagents[operation] = identity
            reactions[self.prefix + '.Reaction.' + ('Input' if role == 'input' else role)] = {
                'role': role, 'material_id': material, 'vessel_id': vessel,
                'activation_material_id': reagents.get('activation'), 'stop_material_id': reagents.get('stop')}
        names = [item['vessel_id'] for item in materials]
        names += [self.prefix + '.' + role + '.ProductTube' for role in ('h3k4me3', 'igg', 'input')]
        names.append(self.prefix + '.ntc.Tube')
        vessels = [{'id': name, 'location': {'kind': 'rack', 'rack_id': self.prefix + '.Rack',
                    'place_id': 'P%02d' % index}} for index, name in enumerate(names, 1)]
        self.origin_location = next(copy.deepcopy(item['location']) for item in vessels if item['id'] == self.vessel_id)
        return materials, vessels, reactions

    def _source(self):
        runtime = json.loads((ROOT / 'model/cutrun-input-sonication.profile.json').read_bytes())
        runtime['enabled'] = True
        runtime['bindings']['input_reaction_id'] = self.reaction_id
        runtime['bindings']['vessel_class'] = 'tube_1_5ml'
        runtime['bindings']['sonicator_place_id'] = 'V01'
        base = json.loads(manual_sources.SOURCE.read_bytes())
        for decision in base['local_decisions'].values():
            decision.update(status='confirmed', value={'fixture_only': self.fixture['id']},
                actor_id=self.actor, confirmed_at=self.fixture['utc_start'], evidence_ref='decision_evidence')
        for name, value in self.fixture['manual_parameters'].items():
            base['parameters'][name].update(value=value, basis='locally_confirmed',
                source_ref='sop', evidence_ref='decision_evidence')
        base['context'].update(culture_id=self.prefix + '.Culture', material_state='fresh_unfixed',
                               condition_id=self.prefix + '.FixtureCondition')
        for role, binding in base['roles'].items():
            binding.update(material_id=None if role == 'ntc' else self.prefix + '.' + role,
                           vessel_id=self.prefix + '.' + role + '.Tube')
        for role, plan in base['qc_plan']['roles'].items():
            plan.update(assay_id=self.prefix + '.QC.' + role, criteria={'fixture_only': True},
                limits={'fixture_only': True}, evidence_ref='decision_evidence')
        base['handover_plan'].update(recipient_id=self.prefix + '.Recipient',
            storage_location={'rack_id': self.prefix + '.Rack', 'place_id': 'P07'},
            conditions='Invented software-fixture storage', evidence_ref='decision_evidence')
        sop = json.loads((ROOT / 'model/cutrun-manual-sop.profile.json').read_bytes())
        sop['qualifications'] = {
            'Fixture.Time': {'kind': 'time', 'source_id': self.time_basis,
                'relationship': None, 'evidence_ref': 'decision_evidence'},
            'Fixture.Temperature': {'kind': 'temperature', 'source_id': self.prefix + '.SpecimenProbe',
                'relationship': 'qualified_proxy', 'evidence_ref': 'decision_evidence'}}
        for name, requirement in sop['phase_requirements'].items():
            duration = self.fixture['manual_parameters']['activation_duration_s'] if name.endswith('.digestion') else 10
            requirement.update(duration_min_s=duration, duration_max_s=duration,
                temperature_min_deg_c=36 if name.endswith('.release') else 3,
                temperature_max_deg_c=38 if name.endswith('.release') else 5,
                time_qualification_ref='Fixture.Time', temperature_qualification_ref='Fixture.Temperature',
                evidence_ref='decision_evidence')
        sop['phase_requirements']['S09.input_preparation'].update({key: self.fixture['phase'][key]
            for key in ('duration_min_s','duration_max_s','temperature_min_deg_c','temperature_max_deg_c')})
        sonic = json.loads(dna_sonication.SOURCE.read_bytes())
        values = {**self.fixture['sonication'], 'device_instance_id': self.device_id,
            'firmware_revision': 'fixture-not-device-firmware', 'vessel_article': 'Unqualified fixture 1.5 mL tube',
            'fill_volume_ul': self.fixture['input_lysate_ul'], 'closed_vessel_fit_evidence_ref': self.prefix + '.Fit',
            'cooling_method': 'Invented fixture cooling', 'amplitude_evidence_ref': self.prefix + '.Amplitude',
            'temperature_reference_vessel_id': self.prefix + '.ReferenceTube',
            'temperature_mapping_evidence_ref': self.prefix + '.TemperatureMapping',
            'empirical_protocol_evidence_ref': self.prefix + '.FictitiousProtocol',
            'input_size_evidence_ref': self.prefix + '.FictitiousSize'}
        for name, value in values.items():
            sonic['parameters'][name].update(value=value, basis='synthetic_assumption',
                source_refs=['hielscher_dna'], note='Invented fixture value; source reference is application background only, not an experimental recommendation.')
        return {'runtime_profile': runtime, 'manual_source': {'base_profile': base, 'sop_profile': sop},
                'sonication_source': sonic}

    def capture(self):
        row = self.journal.connection.execute('SELECT MAX(sequence) FROM events WHERE run_id=?', (self.run_id,)).fetchone()
        last = row[0] or 0
        elapsed = (time.perf_counter_ns() - self._started_ns) / 1_000_000_000
        for sequence in range(self._last_sequence + 1, last + 1):
            self._samples.append({'sequence': sequence, 'elapsed_wall_s': elapsed})
        self._last_sequence = last

    def measurement(self):
        self.capture()
        return {'elapsed_wall_s': (time.perf_counter_ns() - self._started_ns) / 1_000_000_000,
                'events': copy.deepcopy(self._samples), 'basis': 'perf_counter_ns_after_event'}

    def envelope(self, identity=None, *, artifact=None):
        if identity is None:
            self.serial += 1
            identity = self.prefix + '.Observation.%05d' % self.serial
        return {'observation_id': identity, 'source_kind': 'test_fixture',
                'observed_at': {'earliest_utc': self.clock.record['utc'], 'latest_utc': self.clock.record['utc']},
                'source_ref': 'fixture://' + self.run_id,
                'artifact_sha256': None if artifact is None else digest(artifact)}

    def act(self, command, *, artifact=None, observation=None, **data):
        self.last_observation = observation or self.envelope(artifact=artifact)
        try:
            result = self.flow.act(command, self.actor, artifact=artifact,
                                   observation=self.last_observation, **data)
        finally:
            self.capture()
        checkpoint = getattr(self, '_checkpoint', None)
        if checkpoint is not None:checkpoint(command, data)
        return result

    def receipts(self, stage):
        return {name: 'decision_evidence' for name in self.flow.state['definition']['sop_protocol']['stages'][stage]['completion_evidence']}

    def prepare_input(self, *, resume=False):
        def stage_id(name):return self.prefix + '.Stage.' + name
        def stage(name):return self.flow.state['sop']['stages'].get(stage_id(name))
        if not resume or stage('S01') is None:
            self.act('begin_stage', stage_id='S01', reaction_id=None, stage_run_id=stage_id('S01'))
        if not resume or stage('S01')['status'] != 'completed':
            self.act('complete_stage', stage_run_id=stage_id('S01'), receipts=self.receipts('S01'), action_ids=[], reason='Fixture opening only')
        if not resume or stage('S02') is None:
            self.act('begin_stage', stage_id='S02', reaction_id=self.reaction_id, stage_run_id=stage_id('S02'))
        original = self.prefix + '.input'
        lysate = self.prefix + '.InputLysate'
        identity = self.prefix + '.InputPreparation'
        inputs = [{'material_id': original, 'quantity': {'value': self.fixture['initial_cells'], 'unit': 'cells'}, 'consume_all': True}]
        outputs = [{'material_id': lysate, 'kind': 'intermediate', 'vessel_id': self.vessel_id,
                    'role': 'prepared_input_fixture'}]
        booking = self.flow.state['bookings'].get(identity)
        if not resume or booking is None:
            self.act('begin_material_action', intent_id=identity, reaction_id=self.reaction_id, stage_id='S02',
                kind='transformation', inputs=inputs, outputs=outputs, retained_material_id=lysate,
                purpose='Invented fixture input preparation; no lysis or yield prediction')
            self.act('confirm_material_action', intent_id=identity,
                actual_inputs=[{k: item[k] for k in ('material_id','quantity')} for item in inputs],
                actual_outputs=[{'material_id': lysate,
                                 'quantity': {'value': self.fixture['input_lysate_ul'], 'unit': 'uL'}}],
                reason='Explicit fictitious input-volume observation')
        elif booking['outcome'] != 'performed':
            raise TaskError('Existing input preparation requires explicit resolution; no replay')
        if not resume or stage('S02')['status'] != 'completed':
            self.act('complete_stage', stage_run_id=stage_id('S02'), receipts=self.receipts('S02'),
                action_ids=[identity], reason='Fixture input preparation observed')
        if not resume or stage('S09') is None:
            self.act('begin_stage', stage_id='S09', reaction_id=self.reaction_id, stage_run_id=self.stage_run_id)
        self.phase_started_s = stage('S09')['started_at']['monotonic_ns'] / 1_000_000_000
        return self

    def place(self, location):
        observations = self.flow.inventory_observations()
        for item in observations:
            if item['vessel_id'] == self.vessel_id:item['location'] = copy.deepcopy(location)
        return self.act('confirm_inventory', observations=observations)

    def return_to_origin(self):
        return self.place(self.origin_location)

    def begin(self):
        self.place({'kind': 'logical', 'holder_id': self.device_id, 'place_id': 'V01'})
        return self.act('begin_sonication', intent_id=self.intent_id, reaction_id=self.reaction_id,
            stage_run_id=self.stage_run_id, output_material_id=self.output_material_id,
            reason='Persisted fixture intent before any claimed effect')

    def confirm(self):
        plan = self.source['sonication_source']['parameters']
        duration = plan['cycles']['value'] * plan['pulse_on_s']['value'] + (plan['cycles']['value'] - 1) * plan['between_pulses_s']['value']
        self.clock.advance(duration)
        original = json.dumps({'fixture_only': True, 'intent_id': self.intent_id,
            'vessel_id': self.vessel_id, 'claimed_performed': True, 'quantity_ul': self.fixture['input_lysate_ul']}).encode()
        return self.act('confirm_sonication', intent_id=self.intent_id,
            actual_output_quantity={'value': self.fixture['input_lysate_ul'], 'unit': 'uL'},
            observed_vessel_id=self.vessel_id, reason='Fictitious physical-effect observation, no hardware', artifact=original)

    def phase_evidence(self, *, resume=False):
        start = self.phase_started_s
        values = self.fixture['sonication']
        end = start + values['cycles'] * values['pulse_on_s'] + (values['cycles'] - 1) * values['between_pulses_s']
        original = json.dumps({'fixture_only': True, 'time_basis_id': self.time_basis,
            'from_s': start, 'to_s': end, 'temperature_deg_c': self.fixture['phase']['observed_temperature_deg_c']}).encode()
        if not resume or digest(original) not in self.flow.state['sop']['artifacts']:
            self.act('attach_sop_evidence', file_name='synthetic-time-temperature.json', origin='test_fixture', artifact=original)
        identity = {'stage_run_id': self.stage_run_id, 'phase_id': 'S09.input_preparation',
            'reaction_id': self.reaction_id, 'material_id': self.prefix + '.InputLysate',
            'vessel_id': self.vessel_id, 'time_basis_id': self.time_basis,
            'source_kind': 'test_fixture', 'artifact_sha256': digest(original)}
        phase = self.flow.state['sop']['stages'][self.stage_run_id]['phases'][identity['phase_id']]
        if not resume or not phase['times']:
            self.act('record_phase_time', stage_run_id=self.stage_run_id, phase_id=identity['phase_id'],
                record={**identity, 'evidence_id': self.prefix + '.Time', 'qualification_ref': 'Fixture.Time',
                        'start_earliest_s': start, 'start_latest_s': start, 'end_earliest_s': end, 'end_latest_s': end})
        temperature = self.fixture['phase']['observed_temperature_deg_c']
        if not resume or not phase['temperatures']:
            return self.act('record_phase_temperature', stage_run_id=self.stage_run_id, phase_id=identity['phase_id'],
                record={**identity, 'evidence_id': self.prefix + '.Temperature',
                        'source_id': self.prefix + '.SpecimenProbe', 'qualification_ref': 'Fixture.Temperature',
                        'time_qualification_ref': 'Fixture.Time', 'from_earliest_s': start, 'from_latest_s': start,
                        'to_earliest_s': end, 'to_latest_s': end, 'minimum_deg_c': temperature,
                        'maximum_deg_c': temperature, 'uncertainty_deg_c': 0})

    def size_evidence(self):
        identity = self.prefix + '.SizeWithdrawal'
        quantity = {'value': self.fixture['qc_withdrawal_ul'], 'unit': 'uL'}
        self.act('begin_material_action', intent_id=identity, reaction_id=self.reaction_id, stage_id='S09',
            kind='withdrawal', inputs=[{'material_id': self.output_material_id, 'quantity': quantity, 'consume_all': False}],
            outputs=[], purpose='Explicit fixture QC aliquot consumption; no analytical measurement')
        self.act('confirm_material_action', intent_id=identity,
            actual_inputs=[{'material_id': self.output_material_id, 'quantity': quantity}], actual_outputs=[],
            reason='Fixture QC withdrawal observed')
        return self.size_result()

    def size_result(self):
        """Fixture analytical original only; never withdraw a second aliquot."""
        identity = self.prefix + '.SizeWithdrawal'
        original = ('fixture_only,intent_id,material_id,vessel_id,minimum_bp,maximum_bp\ntrue,%s,%s,%s,%s,%s\n' %
            (self.intent_id, self.output_material_id, self.vessel_id,
             self.fixture['size']['minimum_bp'], self.fixture['size']['maximum_bp'])).encode()
        return self.act('record_sonication_size', intent_id=self.intent_id, size_id=self.prefix + '.Size',
            withdrawal_intent_id=identity, minimum_bp=self.fixture['size']['minimum_bp'],
            maximum_bp=self.fixture['size']['maximum_bp'], reason='Invented fragment-size fixture, not NanoDrop/Qubit', artifact=original)

    def complete(self):
        self.return_to_origin()
        return self.act('complete_stage', stage_run_id=self.stage_run_id, receipts=self.receipts('S09'),
            action_ids=[self.intent_id, self.prefix + '.SizeWithdrawal'], reason='Synthetic S09 complete; whole CUT&RUN run remains open')

    def resume(self, gap_seconds=0):
        previous = self.flow.state['clock']['last_sample']
        self.clock = FixtureClock(clock_id=self.time_basis + '.Restart', process_id=self.prefix + '.Writer.2')
        self.clock.record['utc'] = (datetime.fromisoformat(previous['utc'].replace('Z', '+00:00'))
                                   + timedelta(seconds=gap_seconds)).isoformat().replace('+00:00', 'Z')
        self.resume_gap_seconds = gap_seconds
        self.flow = InputSonicationWorkflow.open(self.journal, self.run_id, resume=True, clock=self.clock)
        self.capture()
        return self.flow.state

    def reconcile(self):
        state = self.flow.state
        if state['clock']['gap_required']:
            gap = getattr(self, 'resume_gap_seconds', 0)
            self.act('resolve_clock_gap', minimum_s=gap, maximum_s=gap,
                reason='Explicit fictitious gap declaration; not a measured device duration', evidence_ref='decision_evidence')
        return self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                        reason='Explicit full fixture inventory and workspace reconciliation')

    def finish_cancel(self):
        self.return_to_origin()
        for identity, material in self.flow.state['inventory']['materials'].items():
            if material['disposition_confirmation'] is None:
                self.act('set_disposition', material_id=identity, disposition='retained', reason='Explicit fixture cancellation handover')
        self.act('confirm_inventory', observations=self.flow.inventory_observations())
        self.act('reconcile', observations=self.flow.inventory_observations(), workspace_clear=True,
                 reason='Explicit cancellation inventory reconciliation')
        return self.act('finish_cancel', workspace_clear=True)

    def report(self):
        return self.flow.report()

    @classmethod
    def from_existing(cls, journal, run_id, directory, *, started_ns=None, gap_seconds=25):
        """Resume an existing fixture without creating/resetting any material."""
        validate_run_id(run_id)
        self = cls.__new__(cls)
        self.journal, self.run_id, self.directory = journal, run_id, Path(directory)
        self.fixture = fixture_values()
        scenario = self.fixture['scenarios']['restart']
        self.prefix, self.actor = scenario['prefix'], self.fixture['actor_id']
        self.reaction_id = self.prefix + '.Reaction.Input'
        self.vessel_id, self.device_id = self.prefix + '.input.Tube', self.prefix + '.Sonicator'
        self.stage_run_id, self.intent_id = self.prefix + '.Stage.S09', self.prefix + '.Sonication'
        self.output_material_id = self.prefix + '.FragmentedInput'
        self.time_basis = scenario['clock_id']
        self._started_ns = time.perf_counter_ns() if started_ns is None else started_ns
        self._samples, self._last_sequence = [], 0
        state = journal.state(run_id)[0]
        self.serial = max([int(name.rsplit('.', 1)[1]) for name in state['manual']['observations']
                           if name.startswith(self.prefix + '.Observation.')] or [0])
        self.phase_started_s = state['sop']['stages'][self.stage_run_id]['started_at']['monotonic_ns'] / 1_000_000_000
        self.materials, self.vessels, self.reactions = self._declarations()
        self.evidence_files = {'decision_evidence': self.directory / (run_id + '.fixture-decisions.json')}
        self.source = self._source()
        self.flow = InputSonicationWorkflow(journal, run_id, state['session'])
        self.capture()  # Historical events are observed after the child exited.
        self.resume(gap_seconds=gap_seconds)
        return self


def scenario_record(session, scenario_id):
    return {'scenario_id': scenario_id, 'run_id': session.run_id,
            'report': session.report(), 'measurement': session.measurement()}


def run_scenarios(journal, directory, store_path):
    """Run three independent fixtures, including a real child-process SIGKILL."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    values = fixture_values()
    results = []
    normal = FixtureSession(journal, values['scenarios']['normal']['run_id'], directory / 'normal')
    normal.prepare_input(); normal.begin(); normal.confirm()
    normal.phase_evidence(); normal.size_evidence(); normal.complete()
    results.append(scenario_record(normal, 'normal'))

    cancelled = FixtureSession(journal, values['scenarios']['cancel']['run_id'], directory / 'cancel', scenario_id='cancel')
    cancelled.prepare_input(); cancelled.begin()
    cancelled.act('cancel', reason='Explicit fixture cancellation during an unresolved sonication intent')
    cancelled.act('resolve_sonication', intent_id=cancelled.intent_id, outcome='unknown',
                  reason='Fixture observation cannot establish the physical effect')
    try:
        cancelled.act('finish_cancel', workspace_clear=True)
    except TaskError:
        if not cancelled.flow.state['resources']:
            raise TaskError('Unknown cancellation unexpectedly released resources')
    else:
        raise TaskError('Unknown cancellation was not blocked')
    cancelled.act('resolve_sonication', intent_id=cancelled.intent_id, outcome='not_performed',
                  reason='Separate explicit fixture observation establishes no sonication')
    cancelled.finish_cancel()
    results.append(scenario_record(cancelled, 'cancel'))

    restart_id = values['scenarios']['restart']['run_id']
    restart_directory = directory / 'restart'
    started = time.perf_counter_ns()
    command = [sys.executable, str(ROOT / 'scripts/run_cutrun_input_sonication.py'),
               '--store', str(Path(store_path).resolve()), 'fixture-intent',
               '--directory', str(restart_directory), '--run-id', restart_id, '--scenario-id', 'restart', '--wait']
    log_path = directory / 'restart-worker.log'
    with log_path.open('xb') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(30):
                    raise TaskError('Fixture child did not persist its sonication intent in time')
                line = process.stdout.readline()
            if not line:
                raise TaskError('Fixture child exited before its persisted-intent receipt: ' + log_path.read_text())
            ready = json.loads(line)
            if ready.get('error'):
                raise TaskError('Fixture child could not persist its intent: ' + ready['error'])
            if ready.get('run_id') != restart_id or ready.get('intent_persisted') is not True:
                raise TaskError('Unexpected fixture child receipt')
            process.kill()
            process.wait(timeout=10)
            if process.returncode != -signal.SIGKILL:
                raise TaskError('Fixture child was not terminated with SIGKILL')
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            for stream in (process.stdin, process.stdout):
                if stream is not None:stream.close()
    resumed = FixtureSession.from_existing(journal, restart_id, restart_directory, started_ns=started,
                                          gap_seconds=values['phase']['duration_min_s'])
    if journal.state(restart_id)[0]['bookings'][resumed.intent_id]['outcome'] != 'intent':
        raise TaskError('Restart unexpectedly replayed or confirmed sonication')
    resumed.act('resolve_sonication', intent_id=resumed.intent_id, outcome='unknown',
                reason='Explicit uncertain fixture effect after a real worker-process interruption')
    if not resumed.flow.state['resources']:
        raise TaskError('Uncertain restarted fixture lost its reservations')
    claim = json.dumps({'fixture_only': True, 'observed_after_restart': True,
                        'intent_id': resumed.intent_id, 'claimed_effect': 'performed'}).encode()
    resumed.act('resolve_sonication', intent_id=resumed.intent_id, outcome='performed',
        actual_output_quantity={'value': values['input_lysate_ul'], 'unit': 'uL'},
        observed_vessel_id=resumed.vessel_id,
        reason='Separate fictitious observation resolves the old effect; no command replay', artifact=claim)
    resumed.reconcile()
    resumed.phase_evidence(); resumed.size_evidence(); resumed.complete()
    record = scenario_record(resumed, 'restart')
    record['process_evidence'] = {'worker_exit_code': process.returncode, 'signal': 'SIGKILL',
                                  'intent_persisted_before_kill': True, 'effect_replayed': False}
    results.append(record)
    return results
