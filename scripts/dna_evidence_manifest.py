"""Verify source-bound, local SiLA DNA evidence without changing a workflow.

The archive contains original journal documents, not reserialized expanded
states. Hashes detect accidental changes; this is not a signed audit service.
All evidence writes are confined to exports/dna-evidence/.
"""
import copy
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re

from dna_quantification_ledger import classify_input, remaining
from manual_tasks import TaskError, encoded

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'exports' / 'dna-evidence'
INPUT_FORMAT = 'solidcraftbot.dna-evidence-input/1'
MANIFEST_FORMAT = 'solidcraftbot.dna-evidence-manifest/1'
JOURNAL_FORMAT = 'solidcraftbot.dna-journal-export/1'
TRANSPORT_FORMAT = 'solidcraftbot.dna-loopback-evidence/1'
LABELS = ['Schematische Darstellung', 'synthetische Gerätewerte',
          'SiLA-Loopback ausgeführt', 'ROS nicht ausgeführt',
          'keine Roboterbewegung / keine Hardware']


def require(condition, message):
    if not condition:
        raise TaskError(message)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def is_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def number(value, name):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'Finite nonnegative ' + name + ' required')
    return value


def output_path(path):
    path = Path(path).resolve()
    require(path.is_relative_to(EVIDENCE.resolve()) and path != EVIDENCE.resolve(),
            'DNA evidence output must stay under exports/dna-evidence/<run>/')
    return path


def relative_file(base, value):
    require(isinstance(value, str) and value and not Path(value).is_absolute(),
            'Relative evidence file path required')
    path = (base / value).resolve()
    require(path.is_relative_to(base.resolve()) and path.is_file(),
            'Missing or escaping evidence file: ' + value)
    require(path.suffix.lower() not in {'.key', '.p12', '.pfx'},
            'Private credentials are not evidence artifacts')
    return path


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'),
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError) as error:
        raise TaskError('Invalid evidence JSON: ' + str(path)) from error


def write_json(path, data):
    path = output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return path


def file_record(path, role, base):
    path = Path(path).resolve()
    content = path.read_bytes()
    return {'path': str(path.relative_to(base.resolve())), 'role': role,
            'sha256': sha(content), 'bytes': len(content)}


def _artifact_ids(event):
    found = set()
    if event.get('definition_sha256'):
        found.add(event['definition_sha256'])
    for context in event['state'].get('contexts', {}).values():
        found.update(context.get('local', {}).get('imports', {}))
    return found


def export_journal(journal, run_id, folder):
    """Export a fully verified journal and only its referenced artifact bytes.

    ``folder`` is an evidence run's inputs folder. The SQLite journal is read;
    no resources, states, previous events or artifacts are changed.
    """
    folder = output_path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    journal.history(run_id)
    rows = journal.connection.execute(
        'SELECT sequence, document, sha256 FROM events WHERE run_id=? ORDER BY sequence',
        (run_id,)).fetchall()
    artifacts = set()
    events = []
    for sequence, document, checksum in rows:
        event = json.loads(document)
        artifacts.update(_artifact_ids(event))
        events.append({'sequence': sequence, 'document': document, 'sha256': checksum})
    exported = {}
    for checksum in sorted(artifacts):
        require(is_sha(checksum), 'Invalid journal artifact identity')
        path = folder / 'artifacts' / (checksum + '.bin')
        path.parent.mkdir(exist_ok=True)
        content = journal.artifact(checksum)
        if path.exists():
            require(path.read_bytes() == content, 'Refusing to replace an evidence artifact')
        else:
            path.write_bytes(content)
        exported[checksum] = str(path.relative_to(folder))
    data = {'format': JOURNAL_FORMAT, 'run_id': run_id, 'events': events,
            'chain_head_sha256': rows[-1][2], 'artifacts': exported}
    target = folder / 'journal.json'
    require(not target.exists(), 'Refusing to replace an exported journal')
    return write_json(target, data)


def verify_journal(path):
    data = read_json(path)
    require(data.get('format') == JOURNAL_FORMAT and data.get('events'), 'DNA journal export required')
    artifacts, files = {}, []
    for checksum, relative in data.get('artifacts', {}).items():
        require(is_sha(checksum), 'Invalid exported artifact checksum')
        artifact = relative_file(Path(path).parent, relative)
        require(sha(artifact.read_bytes()) == checksum, 'Exported artifact checksum mismatch')
        artifacts[checksum] = artifact
        files.append(artifact)
    previous, definition_reference = None, None
    events = []
    for sequence, row in enumerate(data['events'], 1):
        document = row.get('document')
        require(isinstance(document, str) and sha(document.encode()) == row.get('sha256'),
                'Journal document checksum mismatch')
        event = json.loads(document)
        require(row.get('sequence') == event.get('sequence') == sequence
                and event.get('run_id') == data['run_id']
                and event.get('previous_sha256') == previous,
                'Journal sequence or hash chain mismatch')
        reference = event.get('definition_sha256')
        if sequence == 1:
            definition_reference = reference
        require(reference == definition_reference, 'Journal definition changed')
        if reference is not None:
            require(event.get('storage_format') == 'solidcraftbot.task-event/2'
                    and reference in artifacts and 'definition' not in event['state'],
                    'Missing immutable journal definition')
            event['state']['definition'] = read_json(artifacts[reference])
        require(isinstance(event['state'].get('definition'), dict), 'Missing workflow definition')
        for checksum in _artifact_ids(event):
            require(checksum in artifacts, 'Missing original journal import bytes')
        event['sha256'] = row['sha256']
        events.append(event)
        previous = row['sha256']
    require(previous == data.get('chain_head_sha256'), 'Journal chain head mismatch')
    return data, events, artifacts, files


def _public_metadata(value):
    if isinstance(value, dict):
        for key, item in value.items():
            require(key.lower() not in {'private_key', 'private_key_pem', 'token',
                                        'access_token', 'password', 'authorization'},
                    'Credentials must not appear in evidence metadata')
            _public_metadata(item)
    elif isinstance(value, list):
        for item in value:
            _public_metadata(item)


def verify_transport(data, events):
    require(data.get('format') == TRANSPORT_FORMAT
            and data.get('transport') == 'SiLA2/TLS/gRPC'
            and data.get('network_executed') is True, 'Executed SiLA TLS evidence required')
    try:
        loopback = ipaddress.ip_address(data.get('host', '')).is_loopback
    except ValueError:
        loopback = False
    require(loopback, 'Only qualified local loopback transport may be claimed')
    _public_metadata(data)
    server = data.get('server', {})
    require(isinstance(server.get('server_uuid'), str) and server['server_uuid']
            and isinstance(server.get('boot_ids'), list) and server['boot_ids']
            and all(isinstance(item, str) and item for item in server['boot_ids'])
            and is_sha(server.get('tls_certificate_sha256')),
            'Public server UUID, boot IDs and certificate fingerprint required')
    by_sequence = {event['sequence']: event for event in events}
    receipts = data.get('receipts')
    require(isinstance(receipts, list) and receipts, 'No completed network transport receipts')
    observations = [event['payload']['server_time_s'] for event in events
                    if event['payload'].get('transport') == 'sila2_tls_loopback'
                    and event['payload'].get('server_uuid') == server['server_uuid']
                    and event['payload'].get('boot_id') in server['boot_ids']
                    and 'server_time_s' in event['payload']]
    require(observations, 'No journal-bound server clock observations')
    first_time = min(number(value, 'server observation time') for value in observations)
    normalized, previous_time, previous_sequence = [], None, 0
    for receipt in receipts:
        event = by_sequence.get(receipt.get('event_sequence'))
        require(event is not None and event['sha256'] == receipt.get('event_sha256')
                and event['run_id'] == receipt.get('run_id'), 'Unbound transport receipt')
        require(event['sequence'] > previous_sequence, 'Transport receipts must be unique and in journal order')
        require(event['kind'] in {'command_finished', 'network.command_finished'},
                'Transport receipt must bind a committed command_finished event')
        payload = event['payload']
        require(payload.get('transport') == 'sila2_tls_loopback'
                and payload.get('evidence') == 'network_receipt'
                and event['state'].get('control', {}).get('server_uuid') == server['server_uuid'],
                'Journal does not record this completion as a SiLA loopback receipt')
        for key in ['command', 'status', 'request_id', 'execution_uuid', 'principal',
                    'server_uuid', 'boot_id', 'server_time_s']:
            require(key in receipt and receipt[key] == payload.get(key),
                    'Transport receipt differs from journal: ' + key)
        require(receipt['server_uuid'] == server['server_uuid']
                and receipt['boot_id'] in server['boot_ids'], 'Transport server identity mismatch')
        require(receipt['status'] in {'completed', 'failed', 'interrupted'},
                'Only explicit terminal command outcomes are finished evidence')
        command = event['state'].get('network', {}).get('commands', {}).get(receipt['request_id'], {})
        require(command.get('transport') == 'sila2_tls_loopback'
                and all(command.get(key) == receipt[key] for key in [
                    'command', 'status', 'principal', 'server_uuid', 'boot_id', 'execution_uuid']),
                'Receipt differs from canonical network command record')
        now = number(receipt['server_time_s'], 'server observation time')
        require(previous_time is None or now >= previous_time, 'Server observation time reversed')
        elapsed = now - first_time
        if 'server_elapsed_s' in receipt:
            require(math.isclose(receipt['server_elapsed_s'], elapsed, abs_tol=1e-9),
                    'Server elapsed time differs from journal observations')
        for key in ['attempt_id', 'context_id']:
            if receipt.get(key) is not None:
                require(receipt[key] in event['state'].get('attempts' if key == 'attempt_id' else 'contexts', {}),
                        'Unknown transport ' + key)
        normalized.append({**receipt, 'server_elapsed_s': elapsed})
        previous_time = now
        previous_sequence = event['sequence']
    expected = {event['sequence'] for event in events
                if event['kind'] in {'command_finished', 'network.command_finished'}
                and event['payload'].get('transport') == 'sila2_tls_loopback'}
    require({item['event_sequence'] for item in normalized} == expected,
            'Transport archive omits finished journal commands')
    return copy.deepcopy(server), normalized, first_time


def verify_report(report, events, artifacts):
    state = events[-1]['state']
    require(report.get('run_id') == state.get('run_id') == events[-1]['run_id'], 'Report run identity mismatch')
    for key in ['status', 'logical_time_s', 'samples', 'attempts', 'contexts', 'bookings',
                'dilutions', 'pending_dilution', 'resources', 'recovery_required']:
        require(report.get(key) == state.get(key), 'Report differs from journal: ' + key)
    for key in ['control', 'network', 'responsible_person_id', 'task_port']:
        if key in state:
            require(report.get(key) == state[key], 'Report differs from journal: ' + key)
    require(report.get('source_files_sha256') == state['definition']['source_files_sha256'],
            'Report source pins differ from journal')
    require(report.get('network_executed') is True and report.get('hardware_executed') is False
            and report.get('robot_motion_executed') is False and report.get('ros_executed', False) is False,
            'Report must distinguish loopback execution from ROS/motion/hardware')
    require(report.get('passed') == (state['status'] == 'completed'
                and not any(sample['accepted_with_flags'] for sample in state['samples'].values())),
            'Report acceptance claim differs from canonical sample decisions')
    require(set(report.get('inventory', {}).get('vessels', {})) == set(state['inventory']['vessels']),
            'Report invents or omits vessel identities')
    for identity, vessel in state['inventory']['vessels'].items():
        observed = report.get('inventory', {}).get('vessels', {}).get(identity, {})
        require(all(observed.get(key) == value for key, value in vessel.items()),
                'Report vessel differs from journal: ' + identity)
        if vessel['kind'] in {'original', 'dilution'}:
            require(observed.get('remaining_volume_ul') == remaining(state, identity),
                    'Report volume differs from canonical ledger')
    attempts = []
    for attempt_id, attempt in state['attempts'].items():
        derived = {'attempt_id': attempt_id, 'sample_id': attempt['sample_id'],
                   'input_vessel_id': attempt['input_vessel_id'],
                   'external_factor': attempt['external_factor'], 'devices': {}}
        for device, result in attempt['results'].items():
            context_id = attempt['contexts'][device]
            context = state['contexts'][context_id]
            require(context['device'] == device and context['source_vessel_id'] == attempt['input_vessel_id']
                    and context['attempt_id'] == attempt_id, 'Result context lineage mismatch')
            checksum = result.get('artifact_sha256')
            require(checksum in artifacts and checksum in context['local']['imports'],
                    'Result lacks its original imported bytes')
            sample_volume = total_volume = None
            if device == 'qubit':
                preparation = context['local']['preparations'][result['preparation_id']]
                sample_volume, total_volume = preparation['sample_volume_ul'], preparation['assay_total_volume_ul']
            else:
                sample_volume = context['local']['measurements'][result['measurement_id']]['withdrawn_volume']['value']
            evaluation = classify_input(result, device, state['definition']['protocol']['assays'][device],
                                        sample_volume_ul=sample_volume, total_volume_ul=total_volume,
                                        external_factor=attempt['external_factor'])
            require(evaluation == attempt['evaluations'][device], 'Result classification is not reproducible')
            derived['devices'][device] = {'context_id': context_id, 'artifact_sha256': checksum,
                                           'evaluation': evaluation}
        attempts.append(derived)
    return state, attempts


def verify_ros_archive(specification, report, state, base):
    """Bind generated interface bytes; generation never implies a ROS build."""
    generated = report.get('ros_interface_generated', False)
    require(type(generated) is bool, 'Explicit generated-interface boolean required')
    if not generated:
        require(specification is None, 'ROS archive supplied for an ungenerated-interface claim')
        return None, []
    require(isinstance(specification, dict)
            and set(specification) == {'report', 'package_directory'},
            'Generated ROS interface claim requires its archived package and report')
    archive_path = relative_file(base, specification['report'])
    archive = read_json(archive_path)
    package = (base / specification['package_directory']).resolve()
    require(package.is_relative_to(base.resolve()) and package.is_dir(), 'Escaping ROS archive directory')
    require(archive.get('format') == 'solidcraftbot.dna-ros-interfaces/1'
            and archive.get('runtime') == {'ros2_built': False, 'ros2_executed': False,
                                          'motion_executed': False, 'hardware_executed': False}
            and report.get('ros_compiled') is False and report.get('ros_executed') is False,
            'Generated interfaces do not establish ROS compilation or execution')
    sources = {**state['definition']['source_files_sha256'],
               **state.get('control', {}).get('source_files_sha256', {})}
    source = relative_file(ROOT, archive['source'])
    require(sha(source.read_bytes()) == archive.get('source_sha256') == sources.get(archive['source']),
            'Archived ROS task protocol is not bound to the workflow source graph')
    for field, relative in [('generator_sha256', 'scripts/build_dna_ros_interfaces.py'),
                             ('decoder_sha256', 'scripts/dna_quantification_tasks.py')]:
        require(archive.get(field) == sha(relative_file(ROOT, relative).read_bytes())
                == sources.get(relative), 'Archived ROS generator/decoder revision mismatch')
    action = 'action/' + archive['action'] + '.action'
    require(set(archive.get('artifacts', {})) == {action, 'CMakeLists.txt', 'package.xml'},
            'Complete archived ROS action/CMake/package artifacts required')
    files = [file_record(archive_path, 'ros_generation_report', base)]
    for relative, checksum in archive['artifacts'].items():
        path = relative_file(package, relative)
        require(is_sha(checksum) and sha(path.read_bytes()) == checksum, 'Archived ROS artifact checksum mismatch')
        files.append(file_record(path, 'generated_ros_interface', base))
    from build_dna_ros_interfaces import action_text
    from dna_quantification_tasks import load_contract
    contract = load_contract()
    require(contract['source_sha256'] == archive['source_sha256']
            and contract['protocol']['ros_package'] == archive['package']
            and contract['protocol']['action_name'] == archive['action']
            and relative_file(package, action).read_text(encoding='utf-8') == action_text(contract),
            'Archived ROS action fields differ from the pinned task contract')
    return {'report': specification['report'], 'package_directory': specification['package_directory'],
            'package': archive['package'], 'action': archive['action'], 'source': archive['source'],
            'source_sha256': archive['source_sha256'], 'generator_sha256': archive['generator_sha256'],
            'decoder_sha256': archive['decoder_sha256'], 'artifacts': archive['artifacts'],
            'ros_compiled': False, 'ros_executed': False}, files


def scene_for(event, elapsed, index, seconds_per_event, last_completed=None):
    state = event['state']
    attempt_id = state.get('active_attempt_id')
    context_id = state.get('active_context_id')
    context = state.get('contexts', {}).get(context_id, {})
    attempt = state.get('attempts', {}).get(attempt_id, {})
    vessel_id = context.get('source_vessel_id') or attempt.get('input_vessel_id')
    vessels = state['inventory']['vessels']
    selected = vessels.get(vessel_id, {})
    goal_id = (event['payload'].get('goal_id') or event['payload'].get('goal', {}).get('goal_id')
               or state.get('task_port', {}).get('pending_goal_id'))
    task = state.get('task_port', {}).get('goals', {}).get(goal_id, {})
    # Show every state-derived identity in the machine-readable scene; the
    # schematic highlights the active input and its actual/home place.
    return {'event_sequence': event['sequence'], 'event_sha256': event['sha256'],
            'event_kind': event['kind'], 'run_id': event['run_id'], 'status': state['status'],
            'request_id': event['payload'].get('request_id'),
            'execution_uuid': event['payload'].get('execution_uuid'),
            'command_status': (event['payload'].get('status')
                               if event['kind'] in {'command_finished', 'network.command_finished'} else None),
            'attempt_id': attempt_id, 'context_id': context_id, 'source_vessel_id': vessel_id,
            'location': selected.get('location'), 'home': selected.get('home'),
            'task_goal_id': goal_id, 'executing_agent_id': task.get('goal', {}).get('executing_agent_id'),
            'worker_boot_id': task.get('worker_boot_id'), 'claim_id': (task.get('claim') or {}).get('claim_id'),
            'last_completed_reference': copy.deepcopy(last_completed),
            'original_vessels': [{'vessel_id': key, 'location': value['location'], 'home': value['home']}
                                 for key, value in vessels.items() if value['kind'] == 'original'],
            'vessels': [{'vessel_id': key, 'sample_id': value.get('sample_id'),
                         'location': value['location'], 'home': value.get('home')}
                        for key, value in vessels.items()],
            'logical_time_s': number(state['logical_time_s'], 'logical workflow time'),
            'server_elapsed_s': elapsed, 'video_time_s': index * seconds_per_event,
            'attempts': [{'attempt_id': key, 'external_factor': value['external_factor'],
                          'input_vessel_id': value['input_vessel_id'],
                          'evaluations': value['evaluations']} for key, value in state['attempts'].items()]}


def derive(input_path, seconds_per_event=0.5):
    input_path = output_path(input_path)
    base = input_path.parent
    data = read_json(input_path)
    require(data.get('format') == INPUT_FORMAT, 'DNA evidence input format required')
    require(isinstance(data.get('commit'), str) and re.fullmatch(r'[0-9a-f]{40}', data['commit']),
            'Full source commit ID required')
    require(type(data.get('working_tree_dirty')) is bool, 'Explicit working-tree state required')
    number(seconds_per_event, 'video seconds per event')
    require(seconds_per_event > 0, 'Positive video interval required')
    records = [file_record(input_path, 'evidence_input', base)]
    for field in ['source_files_sha256', 'fdl_files_sha256']:
        pins = data.get(field)
        require(isinstance(pins, dict) and pins, 'Source and FDL pins required')
        for relative, checksum in pins.items():
            path = relative_file(ROOT, relative)
            require(is_sha(checksum) and sha(path.read_bytes()) == checksum, 'Changed source/FDL pin: ' + relative)
    report_path = relative_file(base, data['report'])
    journal_path = relative_file(base, data['journal_export'])
    transport_path = relative_file(base, data['transport'])
    exported, events, artifacts, artifact_files = verify_journal(journal_path)
    report = read_json(report_path)
    state, attempts = verify_report(report, events, artifacts)
    ros_archive, ros_files = verify_ros_archive(data.get('ros_interfaces'), report, state, base)
    records.extend(ros_files)
    assays = state['definition']['protocol']['assays']
    require(assays['nanodrop']['range'] == {
                'basis': 'selected_input_concentration', 'unit': 'ng/uL', 'lower': 2,
                'upper': 27500, 'lower_kind': 'limit_of_detection_not_lloq'}
            and assays['qubit']['range'] == {
                'basis': 'assay_dna_mass', 'unit': 'ng', 'lower': 0.1, 'upper': 120},
            'Evidence renderer requires the explicitly qualified DNA reference ranges')
    require(all(data['source_files_sha256'].get(path) == checksum
                for path, checksum in state['definition']['source_files_sha256'].items()),
            'Evidence input omits workflow source pins')
    server, receipts, server_origin_s = verify_transport(read_json(transport_path), events)
    logs = data.get('test_logs')
    require(isinstance(logs, list) and logs, 'Executed test logs required')
    for relative in logs:
        path = relative_file(base, relative)
        require(path.stat().st_size > 0, 'Empty test log is not evidence')
        records.append(file_record(path, 'test_log', base))
    records += [file_record(report_path, 'report', base), file_record(journal_path, 'raw_journal', base),
                file_record(transport_path, 'transport_receipts', base)]
    records += [file_record(path, 'journal_artifact', base) for path in artifact_files]
    worker = report.get('worker') if report.get('task_port', {}).get('goals') else None
    labels = LABELS + (['Mock-Worker, kein ROS'] if worker in {'mock', 'MockWorker'} else [])
    scenes, elapsed, completed_contexts, last_completed = [], None, set(), None
    for index, event in enumerate(events):
        payload = event['payload']
        if (payload.get('transport') == 'sila2_tls_loopback'
                and payload.get('server_uuid') == server['server_uuid']
                and payload.get('boot_id') in server['boot_ids'] and 'server_time_s' in payload):
            elapsed = number(payload['server_time_s'], 'server observation time') - server_origin_s
        completed = {identity for identity, context in event['state']['contexts'].items()
                     if context.get('local', {}).get('status') == 'completed'}
        newly_completed = completed - completed_contexts
        if len(newly_completed) == 1:
            identity = next(iter(newly_completed))
            context = event['state']['contexts'][identity]
            last_completed = {'context_id': identity, 'attempt_id': context['attempt_id'],
                              'source_vessel_id': context['source_vessel_id'],
                              'completion_event_sequence': event['sequence']}
        elif newly_completed:
            # A snapshot containing several newly completed contexts does not
            # establish their completion order. Never invent a last identity.
            last_completed = None
        completed_contexts = completed
        scenes.append(scene_for(event, elapsed, index, seconds_per_event, last_completed))
    claims = {'network_executed': True, 'network_scope': 'TLS/gRPC loopback only',
              'ros_executed': False, 'robot_motion_executed': False, 'hardware_executed': False,
              'synthetic_device_values': True, 'schematic_only': True,
              'labels': labels, 'worker': worker,
              'ros_interface_generated': report.get('ros_interface_generated', False),
              'ros_compiled': report.get('ros_compiled', False),
              'network_command_outcomes': {status: sum(item['status'] == status for item in receipts)
                                           for status in ['completed', 'failed', 'interrupted']},
              'nanodrop_reference': {'unit': 'ng/uL', 'lower': 2,
                                      'lower_kind': 'limit_of_detection_not_lloq', 'upper': 27500},
              'qubit_reference': {'basis': 'assay_dna_mass', 'unit': 'ng', 'lower': 0.1, 'upper': 120},
              'time_axes': {'logical': 'workflow synthetic process seconds',
                            'server': 'elapsed from journal-bound server observations; no interpolation',
                            'video': 'event-compressed presentation; no uniform physical time axis',
                            'video_event_interval_s': seconds_per_event}}
    return {'input_path': input_path.name, 'commit': data['commit'],
            'working_tree_dirty': data['working_tree_dirty'],
            'source_files_sha256': data['source_files_sha256'], 'fdl_files_sha256': data['fdl_files_sha256'],
            'journal': {'run_id': exported['run_id'], 'event_count': len(events),
                        'chain_head_sha256': exported['chain_head_sha256']},
            'server': server, 'server_clock_origin_s': server_origin_s,
            'ros_interfaces': ros_archive,
            'receipts': receipts, 'claims': claims,
            'attempts': attempts, 'scenes': scenes, 'files': records,
            'seconds_per_event': seconds_per_event}


def check_manifest(path):
    path = output_path(path)
    manifest = read_json(path)
    require(manifest.get('format') == MANIFEST_FORMAT, 'DNA evidence manifest required')
    for record in manifest.get('files', []):
        artifact = relative_file(path.parent, record['path'])
        require(sha(artifact.read_bytes()) == record['sha256'] and artifact.stat().st_size == record['bytes'],
                'Evidence byte checksum mismatch: ' + record['path'])
    derived = derive(relative_file(path.parent, manifest['input_path']), manifest['seconds_per_event'])
    for key, value in derived.items():
        if key != 'files':
            require(manifest.get(key) == value, 'Evidence semantic claim mismatch: ' + key)
    require(all(record in manifest['files'] for record in derived['files']), 'Missing evidence source byte pins')
    from render_dna_evidence import HEIGHT, WIDTH, probe_video, scene_text, versions
    render = manifest.get('render', {})
    require((render.get('width'), render.get('height')) == (WIDTH, HEIGHT)
            and render.get('frame_count') == len(derived['scenes']), 'Manifest render geometry/count mismatch')
    records = {record['path']: record for record in manifest['files']}
    for index, scene in enumerate(derived['scenes'], 1):
        prefix = 'frames/%06d' % index
        for suffix, role in [('.txt', 'scene_text'), ('.png', 'scene_png')]:
            require(records.get(prefix + suffix, {}).get('role') == role, 'Missing rendered scene byte pin')
        require(relative_file(path.parent, prefix + '.txt').read_text(encoding='utf-8')
                == scene_text(scene, derived['claims']), 'Rendered scene text differs from journal facts')
    require(records.get(render.get('video'), {}).get('role') == 'schematic_video', 'Missing video byte pin')
    require(records.get(render.get('scenes'), {}).get('role') == 'scenes', 'Missing scene index byte pin')
    require(read_json(relative_file(path.parent, render['scenes'])) == derived['scenes'], 'Scene index differs from journal')
    for relative, checksum in manifest.get('implementation_files_sha256', {}).items():
        require(sha(relative_file(ROOT, relative).read_bytes()) == checksum, 'Evidence generator changed: ' + relative)
    require(set(manifest.get('implementation_files_sha256', {})) == {
                'scripts/render_dna_evidence.py', 'scripts/dna_evidence_manifest.py',
                'scripts/dna_quantification_ledger.py'}, 'Missing evidence implementation pins')
    require(manifest.get('tools') == versions(), 'Recorded evidence tool versions changed')
    stream = probe_video(relative_file(path.parent, render['video']))
    require(int(stream['nb_frames']) == len(derived['scenes'])
            and (stream['width'], stream['height']) == (WIDTH, HEIGHT)
            and stream['codec_name'] == render['video_codec']
            and float(stream['duration']) == render['video_duration_s']
            and math.isclose(float(stream['duration']), len(derived['scenes']) * manifest['seconds_per_event'],
                             rel_tol=0, abs_tol=0.0001), 'Encoded video differs from manifest')
    return manifest
