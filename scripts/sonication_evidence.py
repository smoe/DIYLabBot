"""Immutable, journal-derived evidence for local input-sonication fixtures.

Exports are new files under exports/sonication-evidence/.  The checker uses
archived source bytes, not the possibly newer checkout. Hashes detect changed
bytes; they are not signatures or an authenticated laboratory audit service.
"""
import argparse
import ast
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from manual_tasks import TaskError, encoded
from material_ledger import remaining

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'exports/sonication-evidence'
INPUT_FORMAT = 'solidcraftbot.sonication-evidence-input/1'
JOURNAL_FORMAT = 'solidcraftbot.sonication-journal-export/1'
MANIFEST_FORMAT = 'solidcraftbot.sonication-evidence-manifest/1'
REVIEW_FORMAT = 'solidcraftbot.sonication-visual-review/1'
ENGINE = 'input_sonication_mock/1'
LABELS = ['Schematische Darstellung', 'synthetische Beobachtungen / Test-Fixture',
          'SiLA und ROS nicht ausgeführt', 'keine Hardware / keine Roboterbewegung']


def require(condition, message):
    if not condition:
        raise TaskError(message)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def is_sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def number(value, name, *, positive=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    require(valid and (not positive or value > 0), 'Finite nonnegative ' + name + ' required')
    return value


def output_path(value):
    path = Path(value).resolve()
    require(path != EVIDENCE.resolve() and path.is_relative_to(EVIDENCE.resolve()),
            'Sonication evidence must stay under exports/sonication-evidence/<bundle>/')
    return path


def repo_name(value):
    require(isinstance(value, str) and value and not Path(value).is_absolute()
            and '..' not in Path(value).parts and '.git' not in Path(value).parts,
            'Safe relative repository source required')
    return value


def relative_file(base, value):
    repo_name(value)
    base = Path(base).resolve()
    path = (base / value).resolve()
    require(path.is_relative_to(base) and path.is_file(), 'Missing or escaping evidence file: ' + value)
    require(path.suffix.lower() not in {'.key', '.p12', '.pfx'}, 'Private key is not an evidence artifact')
    return path


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate evidence JSON field: ' + key)
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, ValueError) as error:
        raise TaskError('Invalid evidence JSON: ' + str(path)) from error


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n').encode()


def file_record(path, role, base):
    path, base = Path(path).resolve(), Path(base).resolve()
    require(path.is_relative_to(base) and path.is_file(), 'Evidence record escapes its bundle')
    content = path.read_bytes()
    return {'path': str(path.relative_to(base)), 'role': role, 'sha256': sha(content), 'bytes': len(content)}


def write_new(path, content):
    path = output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(content)
    return path


def write_json(path, value):
    return write_new(path, json_bytes(value))


def _put(base, name, content, role, records):
    repo_name(name)
    path = output_path(base / name)
    if path.exists():
        require(path.read_bytes() == content, 'Refusing to replace evidence bytes: ' + name)
    else:
        write_new(path, content)
    records[name] = file_record(path, role, base)
    return name


def _artifact_refs(value, found):
    if isinstance(value, list):
        for item in value:
            _artifact_refs(item, found)
    elif isinstance(value, dict):
        for name, item in value.items():
            if name in {'artifact_sha256', 'definition_sha256'} and item is not None:
                require(is_sha(item), 'Invalid explicit original-artifact reference')
                found.add(item)
            elif name == 'initial_artifact_sha256':
                require(isinstance(item, list) and all(is_sha(part) for part in item),
                        'Invalid original source-artifact manifest')
                found.update(item)
            else:
                _artifact_refs(item, found)


def artifact_refs(event):
    found = set()
    _artifact_refs(event, found)
    state = event['state']
    for mapping in (state.get('manual', {}).get('qc_artifacts', {}),
                    state.get('sop', {}).get('artifacts', {})):
        require(isinstance(mapping, dict) and all(is_sha(part) for part in mapping),
                'Invalid owned original-artifact map')
        found.update(mapping)
    return found


def _raw_export(journal, run_id, base, label, records):
    journal.history(run_id)  # The authoritative reader verifies the complete chain.
    rows = journal.connection.execute(
        'SELECT sequence, document, sha256 FROM events WHERE run_id=? ORDER BY sequence', (run_id,)).fetchall()
    require(bool(rows), 'An existing journal run is required')
    definition = None
    references, exported = set(), []
    for sequence, document, checksum in rows:
        event = json.loads(document)
        reference = event.get('definition_sha256')
        if reference:
            if definition is None:
                definition = json.loads(journal.artifact(reference))
            expanded = {**event, 'state': {**event['state'], 'definition': definition}}
        else:
            expanded = event
        references.update(artifact_refs(expanded))
        exported.append({'sequence': sequence, 'document': document, 'sha256': checksum})
    artifacts = {}
    for checksum in sorted(references):
        content = journal.artifact(checksum)
        require(sha(content) == checksum, 'Corrupt original journal artifact')
        artifacts[checksum] = _put(base, 'inputs/artifacts/' + checksum + '.bin', content,
                                   'journal_original', records).removeprefix('inputs/')
    data = {'format': JOURNAL_FORMAT, 'run_id': run_id, 'events': exported,
            'chain_head_sha256': rows[-1][2], 'artifacts': artifacts}
    name = 'inputs/journal-' + label + '.json'
    _put(base, name, json_bytes(data), 'raw_journal', records)
    return name


def verify_journal(path):
    data = read_json(path)
    require(data.get('format') == JOURNAL_FORMAT and isinstance(data.get('events'), list)
            and data['events'], 'Sonication journal export required')
    artifacts = {}
    for checksum, name in data.get('artifacts', {}).items():
        require(is_sha(checksum), 'Invalid artifact identity')
        artifact = relative_file(Path(path).parent, name)
        require(sha(artifact.read_bytes()) == checksum, 'Original artifact checksum mismatch')
        artifacts[checksum] = artifact
    previous, reference, definition = None, None, None
    events = []
    for sequence, row in enumerate(data['events'], 1):
        document = row.get('document')
        require(isinstance(document, str) and sha(document.encode()) == row.get('sha256'),
                'Raw journal document checksum mismatch')
        event = json.loads(document)
        require(row.get('sequence') == event.get('sequence') == sequence
                and event.get('run_id') == data.get('run_id')
                and event.get('previous_sha256') == previous, 'Journal sequence/run/hash chain mismatch')
        if sequence == 1:
            reference = event.get('definition_sha256')
            require(is_sha(reference) and reference in artifacts, 'Immutable definition original required')
            definition = read_json(artifacts[reference])
        require(event.get('definition_sha256') == reference
                and event.get('storage_format') == 'solidcraftbot.task-event/2'
                and 'definition' not in event['state'], 'Journal immutable definition changed')
        event['state']['definition'] = copy.deepcopy(definition)
        state = event['state']
        require(state.get('format') == 'solidcraftbot.material-workflow-state/3'
                and definition.get('profile', {}).get('type') == ENGINE
                and definition.get('clock_source_kind') == 'test_clock'
                and state.get('manual', {}).get('engine') == ENGINE,
                'Only the explicit input-sonication fixture engine is supported')
        context = state.get('observation_context')
        require(context is None or context.get('source_kind') == 'test_fixture',
                'A fixture archive cannot claim laboratory observations')
        require(artifact_refs(event) <= set(artifacts), 'Missing owned original-artifact bytes')
        if any(item['outcome'] in {'intent', 'unknown'} for item in state['bookings'].values()):
            require(bool(state['resources']), 'Unclear material effects cannot release root resources')
        event['sha256'] = row['sha256']
        events.append(event)
        previous = row['sha256']
    require(previous == data.get('chain_head_sha256'), 'Journal chain head mismatch')
    return data, events, artifacts


def _source_bytes(journal, source_root, name, checksum):
    path = (source_root / repo_name(name)).resolve()
    require(path.is_relative_to(source_root.resolve()), 'Source snapshot escapes its selected root')
    if path.is_file():
        content = path.read_bytes()
        if sha(content) == checksum:
            return content
    # Fixture SOP originals may intentionally differ from today's checkout.
    content = journal.artifact(checksum)
    require(sha(content) == checksum, 'Source snapshot checksum mismatch: ' + name)
    return content


def _implementation_files():
    pending = ['scripts/sonication_evidence.py', 'scripts/render_sonication_evidence.py']
    found = {}
    while pending:
        name = pending.pop()
        if name in found:
            continue
        content = (ROOT / name).read_bytes()
        found[name] = content
        for node in ast.walk(ast.parse(content, filename=name)):
            modules = ([item.name for item in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                target = 'scripts/' + module.split('.')[0] + '.py'
                if (ROOT / target).is_file() and target not in found:
                    pending.append(target)
    return found


def _git_provenance(base, records):
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}
    def git(*args):
        return subprocess.check_output(['git', '-C', str(ROOT), *args], env=env)
    changed = {name.decode() for name in git('diff', '--name-only', '-z', 'HEAD').split(b'\0') if name}
    changed.update(name.decode() for name in git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0') if name)
    snapshots, hashes = {}, {}
    for name in sorted(changed):
        path = ROOT / repo_name(name)
        if path.is_file():
            content = path.read_bytes()
            snapshots[name] = _put(base, 'inputs/working-tree/' + name, content, 'working_source', records)
            hashes[name] = sha(content)
        else:
            hashes[name] = None
    patch = git('diff', '--binary', 'HEAD')
    patch_name = _put(base, 'inputs/working-tree.patch', patch, 'working_tree_diff', records)
    return {'base_commit': git('rev-parse', 'HEAD').decode().strip(),
            'working_tree_dirty': bool(changed), 'working_files_sha256': hashes,
            'working_snapshots': snapshots, 'tracked_diff_sha256': sha(patch),
            'tracked_diff_path': patch_name,
            'assignment': 'Base commit plus these archived working bytes; not an uncreated future commit'}


def export_bundle(journal, scenarios, directory, test_logs=None, *, source_root=None):
    """Archive independent fixture runs without changing their journal/store."""
    base = output_path(directory)
    require(isinstance(scenarios, list) and scenarios, 'Explicit fixture scenarios required')
    labels, run_ids = set(), set()
    for item in scenarios:
        require({'scenario_id', 'run_id', 'report', 'measurement'} <= set(item)
                <= {'scenario_id', 'run_id', 'report', 'measurement', 'process_evidence'},
                'Explicit scenario fields required')
        label = item['scenario_id']
        require(isinstance(label, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', label)
                and label not in labels and item['run_id'] not in run_ids, 'Unique scenario/run identities required')
        labels.add(label);run_ids.add(item['run_id'])
    base.mkdir(parents=True, exist_ok=False)
    records, descriptors = {}, []
    source_root = ROOT if source_root is None else Path(source_root).resolve()
    for item in scenarios:
        label = item['scenario_id']
        journal_name = _raw_export(journal, item['run_id'], base, label, records)
        unused, events, artifacts = verify_journal(base / journal_name)
        source_pins = events[-1]['state']['definition']['source_files_sha256']
        sources = {}
        for name, checksum in sorted(source_pins.items()):
            require(is_sha(checksum), 'Invalid runtime source pin')
            content = _source_bytes(journal, source_root, name, checksum)
            sources[name] = _put(base, 'inputs/sources/' + checksum + '/' + repo_name(name),
                                 content, 'source_snapshot', records)
        report_name, measurement_name = 'inputs/report-' + label + '.json', 'inputs/measurement-' + label + '.json'
        _put(base, report_name, json_bytes(item['report']), 'root_report', records)
        _put(base, measurement_name, json_bytes(item['measurement']), 'wall_measurement', records)
        descriptor = {'scenario_id': label, 'run_id': item['run_id'], 'journal': journal_name,
            'report': report_name, 'measurement': measurement_name,
            'source_files_sha256': source_pins, 'source_snapshots': sources}
        if 'process_evidence' in item:
            descriptor['process_evidence'] = _put(base, 'inputs/process-' + label + '.json',
                json_bytes(item['process_evidence']), 'local_process_evidence', records)
        descriptors.append(descriptor)
    implementation = {}
    for name, content in sorted(_implementation_files().items()):
        implementation[name] = {'sha256': sha(content), 'path': _put(base,
            'inputs/implementation/' + name, content, 'implementation_source', records)}
    logs = {}
    for label, path in sorted((test_logs or {}).items()):
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', label) is not None, 'Safe test-log identity required')
        logs[label] = _put(base, 'inputs/test-logs/' + label + '.log', Path(path).read_bytes(), 'test_log', records)
    provenance = _git_provenance(base, records)
    data = {'format': INPUT_FORMAT, 'scenarios': descriptors, 'test_logs': logs,
            'implementation_sources': implementation, 'provenance': provenance,
            'files': sorted(records.values(), key=lambda item: item['path'])}
    path = write_json(base / 'evidence-input.json', data)
    derive(path)
    return path


def _measurement(value, events):
    require(set(value) == {'basis', 'elapsed_wall_s', 'events'}
            and value['basis'] == 'perf_counter_ns_after_event', 'Explicit measured local fixture runtime required')
    total = number(value['elapsed_wall_s'], 'measured fixture runtime')
    require(isinstance(value['events'], list) and len(value['events']) == len(events), 'Wall samples must cover every event')
    previous, result = 0, {}
    for sequence, item in enumerate(value['events'], 1):
        require(set(item) == {'sequence', 'elapsed_wall_s'} and type(item['sequence']) is int
                and item['sequence'] == sequence, 'Wall sample sequence mismatch')
        current = number(item['elapsed_wall_s'], 'event wall sample')
        require(previous <= current <= total, 'Measured wall samples are not monotone or exceed runtime')
        result[sequence], previous = current, current
    return result


def _verify_process(process, events):
    require(set(process) == {'worker_exit_code', 'signal', 'intent_persisted_before_kill', 'effect_replayed'}
            and type(process['worker_exit_code']) is int and process['worker_exit_code'] == -9
            and process['signal'] == 'SIGKILL' and process['intent_persisted_before_kill'] is True
            and process['effect_replayed'] is False, 'Explicit local child-SIGKILL evidence required')
    identifiers = set().union(*[set(_sonication_actions(event['state'])) for event in events])
    require(len(identifiers) == 1, 'Interrupted fixture must retain exactly one canonical sonication intent')
    identity = next(iter(identifiers))
    first = next(event for event in events if identity in _sonication_actions(event['state']))
    reopened = [event for event in events if event['kind'] == 'manual_session_opened'
                and event['sequence'] > first['sequence']
                and event['state']['bookings'].get(identity, {}).get('outcome') in {'intent', 'unknown'}]
    require(first['state']['bookings'][identity]['outcome'] == 'intent' and reopened,
            'Child-process evidence requires a persisted intent and later explicit uncertain resume')
    previous, performed_at = None, []
    for event in events:
        outcome = event['state']['bookings'].get(identity, {}).get('outcome')
        if outcome == 'performed' and previous != 'performed':
            performed_at.append(event['sequence'])
        previous = outcome
    require(len(performed_at) == 1 and performed_at[0] > reopened[0]['sequence'],
            'Interrupted fixture must confirm one effect only after explicit resume')


def _sonication_actions(state):
    return {identity: action for identity, action in state['manual']['actions'].items()
            if 'sonication' in action}


def _intent_view(state, identity):
    action = state['manual']['actions'][identity]
    meta = action['sonication']
    required = {'stage_run_id', 'reaction_id', 'material_before_id', 'material_after_id',
                'vessel_id', 'pulse_plan', 'size_records', 'intent_session', 'physical_receipt',
                'quantity_before', 'original_rack_location', 'source_pins_sha256'}
    require(isinstance(meta, dict) and required <= set(meta), 'Complete canonical sonication metadata required')
    booking = state['bookings'].get(identity)
    require(booking is not None, 'Sonication intent has no canonical booking')
    stage = state['sop']['stages'].get(meta['stage_run_id'])
    require(stage is not None and stage['stage_id'] == 'S09'
            and stage['reaction_id'] == meta['reaction_id']
            and state['manual']['reactions'][meta['reaction_id']]['role'] == 'input',
            'Sonication metadata must bind the separate S09 input')
    pulse = meta['pulse_plan']
    cycles, on, pause = pulse['cycles'], pulse['pulse_on_s'], pulse['between_pulses_s']
    number(cycles, 'fixture pulse count', positive=True)
    require(cycles == int(cycles), 'Integer fixture pulse count required')
    number(on, 'pulse on seconds', positive=True);number(pause, 'between-pulse seconds')
    require(pulse['total_on_s'] == cycles * on
            and pulse['total_between_pulses_s'] == (cycles - 1) * pause
            and pulse['nominal_elapsed_s'] == cycles * on + (cycles - 1) * pause
            and pulse['energy_delivered_j'] is None and pulse['executed'] is False,
            'Pulse plan arithmetic mismatch')
    require(meta.get('source_pins_sha256') == sha(encoded(state['definition']['source_files_sha256']).encode()),
            'Sonication intent source binding changed')
    require(isinstance(meta['size_records'], dict), 'Identified size observations required')
    for size_id, item in meta['size_records'].items():
        record = item['observation']
        require(record['size_id'] == size_id and record['material_id'] == meta['material_after_id']
                and record['vessel_id'] == meta['vessel_id'] and record['unit'] == 'bp'
                and item['biological_acceptance'] is False, 'Size evidence identity/unit mismatch')
        minimum = number(record['minimum_bp'], 'size minimum bp', positive=True)
        maximum = number(record['maximum_bp'], 'size maximum bp', positive=True)
        require(minimum <= maximum and booking['outcome'] == 'performed', 'Size evidence needs ordered values and confirmed sonication')
        withdrawal = state['bookings'].get(record['withdrawal_intent_id'])
        require(withdrawal is not None and withdrawal['outcome'] == 'performed'
                and withdrawal['request']['kind'] == 'withdrawal' and len(withdrawal['actual_inputs']) == 1
                and withdrawal['actual_inputs'][0]['material_id'] == meta['material_after_id'],
                'Size evidence lacks its confirmed canonical QC consumption')
        quantity = withdrawal['actual_inputs'][0]['quantity']
        require(quantity['unit'] == 'uL' and number(quantity['value'], 'QC withdrawal uL', positive=True),
                'Size evidence requires an observed positive QC volume')
        target = state['definition']['sonication_plan']['fragment_size']
        comparison = target['comparison_target'];column = target['column_maximum_exclusive_bp']['value']
        conforms = minimum >= comparison['minimum'] and maximum <= comparison['maximum']
        conforms = bool(conforms and (column is None or maximum < column))
        require(item['fixture_range_conformant'] is conforms, 'Size fixture comparison differs from its bound source')
    return {**copy.deepcopy(meta), 'booking_outcome': booking['outcome'],
            'continuation_uncertain': (booking['outcome'] in {'intent', 'unknown'}
                                       and meta['intent_session'] != state['session'])}


def _verify_report(report, events):
    state = events[-1]['state']
    require(report.get('run_id') == events[-1]['run_id'] and report.get('trace') == events,
            'Root report trace differs from original journal')
    for name in ('status', 'inventory', 'bookings', 'resources', 'clock', 'pending_operation', 'recovery_required'):
        require(report.get(name) == state[name], 'Root report differs from committed ' + name)
    require(report.get('source_files_sha256') == state['definition']['source_files_sha256'], 'Report source pins changed')
    balances = {identity: remaining(state, identity) for identity in state['inventory']['materials']}
    require(report.get('remaining') == balances, 'Report material balance differs from root ledger')
    require(report.get('execution_ready') is False and report.get('hardware_executed') is False
            and report.get('network_executed') is False, 'Fixture report cannot claim physical/network readiness')
    details = report.get('sonication')
    require(isinstance(details, dict) and details.get('mode') == 'test_fixture_only', 'Explicit sonication fixture report required')
    intents = _sonication_actions(state)
    require(set(details.get('intents', {})) == set(intents), 'Report sonication intents differ from canonical actions')
    for identity in intents:
        expected = _intent_view(state, identity)
        require(details['intents'][identity] == expected,
                'Report sonication identity/plan/outcome differs from canonical action')
    require(details['enabled'] is state['definition']['runtime_profile']['enabled']
            and details['source_pins'] == state['definition']['source_files_sha256']
            and details['pending_intents'] == [identity for identity in intents
                if state['bookings'][identity]['outcome'] in {'intent', 'unknown'}],
            'Report optional/pending/source binding differs from root')
    require(not any(details.get('flags', {}).values()), 'Sonication fixture cannot claim hardware/ROS/SiLA effects')
    return balances


def _scene(event, scenario, elapsed, index, interval, focus):
    state = event['state']
    inputs = [(identity, reaction) for identity, reaction in state['manual']['reactions'].items() if reaction['role'] == 'input']
    require(len(inputs) == 1, 'Exactly one independent input reaction is required')
    reaction_id, reaction = inputs[0]
    material_id = reaction['current_material_id']
    material = state['inventory']['materials'][material_id]
    vessel_id = material['vessel_id']
    vessel = state['inventory']['vessels'].get(vessel_id)
    intent = None if focus is None else _intent_view(state, focus)
    clock = state['clock']
    lower = number(clock['lower_s'], 'process time lower bound')
    upper = clock['upper_s']
    require(upper is None or number(upper, 'process time upper bound') >= lower, 'Reversed process interval')
    return {'scenario_id': scenario, 'run_id': event['run_id'], 'event_sequence': event['sequence'],
            'event_sha256': event['sha256'], 'event_kind': event['kind'], 'root_status': state['status'],
            'reaction_id': reaction_id, 'material_id': material_id, 'vessel_id': vessel_id,
            'location': None if vessel is None else copy.deepcopy(vessel['location']),
            'remaining': remaining(state, material_id), 'resources': copy.deepcopy(state['resources']),
            'intent_id': focus, 'intent': intent,
            'process_time_s': {'minimum': lower, 'maximum': upper, 'basis': 'synthetic test clock'},
            'measured_fixture_elapsed_s': elapsed, 'video_time_s': index * interval,
            'phase_evidence': {identity: copy.deepcopy(stage['phases']) for identity, stage in state['sop']['stages'].items()
                               if stage['stage_id'] == 'S09'},
            'pending_operation': copy.deepcopy(state['pending_operation'])}


def _verify_records(base, rows):
    require(isinstance(rows, list) and rows, 'Evidence file inventory required')
    result = {}
    for record in rows:
        require(set(record) == {'path', 'role', 'sha256', 'bytes'} and record['path'] not in result,
                'Unique explicit evidence file records required')
        path = relative_file(base, record['path'])
        require(is_sha(record['sha256']) and type(record['bytes']) is int
                and sha(path.read_bytes()) == record['sha256'] and path.stat().st_size == record['bytes'],
                'Evidence byte checksum mismatch: ' + record['path'])
        result[record['path']] = record
    return result


def derive(input_path, seconds_per_event=0.5):
    input_path = output_path(input_path)
    interval = number(seconds_per_event, 'video event interval', positive=True)
    data = read_json(input_path);base = input_path.parent
    require(data.get('format') == INPUT_FORMAT, 'Sonication evidence input required')
    records = _verify_records(base, data['files'])
    def listed(name):
        require(name in records, 'Referenced evidence file is not byte-pinned: ' + name)
        return relative_file(base, name)
    require({'scripts/sonication_evidence.py', 'scripts/render_sonication_evidence.py',
             'scripts/manual_tasks.py', 'scripts/material_ledger.py', 'scripts/render_dna_evidence.py'}
            <= set(data['implementation_sources']), 'Missing evidence implementation source closure')
    for name, value in data['implementation_sources'].items():
        repo_name(name)
        require(sha(listed(value['path']).read_bytes()) == value['sha256'], 'Archived implementation pin changed')
    provenance = data['provenance']
    require(re.fullmatch('[0-9a-f]{40}', provenance.get('base_commit', '')) is not None,
            'Recorded base commit required')
    require(sha(listed(provenance['tracked_diff_path']).read_bytes()) == provenance['tracked_diff_sha256'],
            'Archived working diff changed')
    for name, checksum in provenance['working_files_sha256'].items():
        repo_name(name)
        if checksum is not None:
            require(sha(listed(provenance['working_snapshots'][name]).read_bytes()) == checksum,
                    'Archived working source changed')
    for name in data['test_logs'].values():listed(name)
    scenes, summaries, labels, run_ids = [], [], set(), set()
    for item in data['scenarios']:
        require(item['scenario_id'] not in labels and item['run_id'] not in run_ids, 'Scenario/run identity reused')
        labels.add(item['scenario_id']);run_ids.add(item['run_id'])
        exported, events, artifacts = verify_journal(listed(item['journal']))
        for artifact in artifacts.values():
            require(str(artifact.relative_to(base)) in records, 'Journal original lacks an evidence byte pin')
        require(exported['run_id'] == item['run_id'], 'Scenario run differs from journal')
        report = read_json(listed(item['report']))
        _verify_report(report, events)
        pins = events[-1]['state']['definition']['source_files_sha256']
        require(item['source_files_sha256'] == pins and set(item['source_snapshots']) == set(pins), 'Incomplete runtime source snapshots')
        for name, checksum in pins.items():
            require(sha(listed(item['source_snapshots'][name]).read_bytes()) == checksum,
                    'Archived runtime source pin changed: ' + name)
        samples = _measurement(read_json(listed(item['measurement'])), events)
        process = None
        if 'process_evidence' in item:
            process = read_json(listed(item['process_evidence']))
            _verify_process(process, events)
        known, focus = set(), None
        for event in events:
            actions = set(_sonication_actions(event['state']))
            added = sorted(actions - known)
            if added:focus = added[-1]
            require(focus is None or focus in actions, 'Canonical sonication intent disappeared')
            known = actions
            scene = _scene(event, item['scenario_id'], samples[event['sequence']], len(scenes), interval, focus)
            scene['process_evidence'] = process
            scenes.append(scene)
        summaries.append({'scenario_id': item['scenario_id'], 'run_id': item['run_id'],
            'event_count': len(events), 'chain_head_sha256': exported['chain_head_sha256'],
            'root_status': events[-1]['state']['status'], 'resources_held': bool(events[-1]['state']['resources']),
            'sonication': copy.deepcopy(report['sonication']), 'process_evidence': process})
    require(scenes, 'At least one journal-derived scene required')
    records[input_path.name] = file_record(input_path, 'evidence_input', base)
    return {'input_path': input_path.name, 'provenance': provenance, 'scenarios': summaries,
            'implementation_sources': data['implementation_sources'], 'test_logs': data['test_logs'],
            'claims': {'labels': LABELS, 'network_executed': False, 'sila_executed': False,
                'ros_executed': False, 'hardware_executed': False, 'robot_motion_executed': False,
                'scope': 'local root-journal fixture only',
                'time_axes': {'process': 'synthetic root interval', 'wall': 'measured local fixture runtime',
                    'video': 'independent event presentation clock', 'video_event_interval_s': interval}},
            'scenes': scenes, 'seconds_per_event': interval,
            'files': sorted(records.values(), key=lambda item: item['path'])}


def inspection_frames(count):
    return ['frames/%06d.png' % index for index in sorted({1, (count + 1) // 2, count})]


def check_manifest(path):
    path = output_path(path);base = path.parent;manifest = read_json(path)
    require(manifest.get('format') == MANIFEST_FORMAT, 'Sonication evidence manifest required')
    records = _verify_records(base, manifest.get('files'))
    derived = derive(relative_file(base, manifest['input_path']), manifest['seconds_per_event'])
    require(set(manifest) == set(derived) | {'format', 'tools', 'render'}, 'Unknown or missing manifest fields')
    for name, value in derived.items():
        if name != 'files':
            require(manifest.get(name) == value, 'Evidence semantic claim mismatch: ' + name)
    require(all(records.get(item['path']) == item for item in derived['files']), 'Missing immutable evidence input pins')
    from render_sonication_evidence import HEIGHT, WIDTH, probe_video, scene_cards
    render = manifest['render']
    require(set(render) == {'width', 'height', 'frame_count', 'video', 'scenes', 'cards',
        'renderer_source', 'renderer_binary', 'tool_versions', 'video_duration_s',
        'video_codec', 'visual_review'}, 'Unknown or missing render fields')
    require((render['width'], render['height']) == (WIDTH, HEIGHT)
            and render['frame_count'] == len(derived['scenes']), 'Render dimensions/frame count changed')
    for index, card in enumerate(scene_cards(derived), 1):
        prefix = 'frames/%06d' % index
        require(records.get(prefix + '.txt', {}).get('role') == 'scene_text'
                and relative_file(base, prefix + '.txt').read_text() == card['body'], 'Rendered text differs from journal scene')
        require(records.get(prefix + '.png', {}).get('role') == 'scene_png', 'Missing pinned scene PNG')
        image = relative_file(base, prefix + '.png').read_bytes()
        require(image[:8] == b'\x89PNG\r\n\x1a\n' and image[12:16] == b'IHDR'
                and int.from_bytes(image[16:20], 'big') == WIDTH
                and int.from_bytes(image[20:24], 'big') == HEIGHT, 'Scene PNG pixel dimensions changed')
    require(read_json(relative_file(base, render['scenes'])) == derived['scenes'], 'Scene index differs from journal')
    require(read_json(relative_file(base, render['cards'])) == scene_cards(derived), 'Render cards differ from journal')
    for field, role in [('video', 'schematic_video'), ('scenes', 'scenes'), ('cards', 'renderer_input'),
                        ('renderer_source', 'native_renderer_source'), ('renderer_binary', 'compiled_renderer'),
                        ('tool_versions', 'tool_versions')]:
        require(records.get(render[field], {}).get('role') == role, 'Missing pinned render artifact: ' + field)
    require(manifest['tools'] == read_json(relative_file(base, render['tool_versions'])),
            'Recorded tool versions differ from their original bytes')
    stream = probe_video(relative_file(base, render['video']))
    require(int(stream['nb_frames']) == len(derived['scenes'])
            and (stream['width'], stream['height']) == (WIDTH, HEIGHT)
            and stream['codec_name'] == render['video_codec']
            and math.isclose(float(stream['duration']), render['video_duration_s'], abs_tol=0.0001, rel_tol=0)
            and math.isclose(float(stream['duration']), len(derived['scenes']) * derived['seconds_per_event'],
                             abs_tol=0.0001, rel_tol=0), 'Encoded video differs from manifest')
    review = render['visual_review']
    require(set(review) == {'reviewed', 'frames', 'record', 'source_manifest'}, 'Explicit visual review fields required')
    require(review['frames'] == inspection_frames(len(derived['scenes'])), 'Visual inspection frame selection changed')
    require(type(review['reviewed']) is bool, 'Explicit visual review status required')
    if review['reviewed']:
        require(review['source_manifest'] != path.name
                and read_json(relative_file(base, review['source_manifest']))['render']['visual_review']['reviewed'] is False,
                'Review must bind a distinct unreviewed manifest')
        original = check_manifest(relative_file(base, review['source_manifest']))
        require(original['render']['visual_review']['reviewed'] is False, 'Review must bind an unreviewed original manifest')
        record = read_json(relative_file(base, review['record']))
        require(records.get(review['source_manifest'], {}).get('role') == 'pre_review_manifest'
                and records.get(review['record'], {}).get('role') == 'visual_review', 'Visual review original files must be pinned')
        require(all(original[name] == manifest[name] for name in derived if name != 'files')
                and original['tools'] == manifest['tools'], 'Visual review cannot change the source evidence')
        require(record['format'] == REVIEW_FORMAT and record['source_manifest_sha256'] ==
                sha(relative_file(base, review['source_manifest']).read_bytes()), 'Visual review source manifest mismatch')
        require(record['inspected_frames'] == [{'path': name, 'sha256': records[name]['sha256']}
                for name in review['frames']] and isinstance(record['note'], str) and record['note'].strip(),
                'Visual review must name the actual first/middle/last image hashes')
    else:
        require(review['record'] is None and review['source_manifest'] is None, 'Unperformed visual review cannot cite evidence')
    return manifest


def record_visual_review(path, *, inspected_frames, note):
    """Call only after actual visual inspection; preserve the first manifest."""
    path = output_path(path);manifest = check_manifest(path);base = path.parent
    require(manifest['render']['visual_review']['reviewed'] is False, 'Visual review already recorded')
    expected = inspection_frames(manifest['render']['frame_count'])
    require(inspected_frames == expected and isinstance(note, str) and note.strip(), 'Explicit inspected frame paths and review note required')
    records = {item['path']: item for item in manifest['files']}
    record = {'format': REVIEW_FORMAT, 'source_manifest_sha256': sha(path.read_bytes()),
              'inspected_frames': [{'path': name, 'sha256': records[name]['sha256']} for name in expected],
              'note': note, 'scope': 'Visual layout inspection; no hardware or biological qualification'}
    review_path = write_json(base / 'visual-review.json', record)
    manifest['files'] += [file_record(path, 'pre_review_manifest', base), file_record(review_path, 'visual_review', base)]
    manifest['render']['visual_review'] = {'reviewed': True, 'frames': expected,
        'record': review_path.name, 'source_manifest': path.name}
    result = write_json(base / 'reviewed-manifest.json', manifest)
    check_manifest(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--check', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        manifest = check_manifest(args.manifest)
        print(json.dumps({'checked': True, 'scenarios': len(manifest['scenarios']),
                          'frames': manifest['render']['frame_count'],
                          'visual_reviewed': manifest['render']['visual_review']['reviewed']}))
        return 0
    except (TaskError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
