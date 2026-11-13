"""New, immutable S09 SiLA evidence; historical fixture media remain unchanged.

Hashes bind archived bytes and observations. They are not signatures, device
measurements or laboratory qualification. The underlying S09 report always
remains test_fixture_only, even when TLS loopback control was executed.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import build_cutrun_input_sonication_sila2 as contract
import sonication_evidence as fixture_evidence
from manual_tasks import Journal, TaskError, encoded
from material_ledger import remaining
from render_dna_evidence import probe_video, run, versions
from render_sonication_evidence import SWIFT, WIDTH, HEIGHT
from sonication_evidence import (file_record, is_sha, json_bytes, read_json,
    relative_file, repo_name, require, sha, verify_journal)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'exports/sonication-evidence'
FORMAT = 'solidcraftbot.s09-sila2-evidence/1'
INTERVAL = 0.5
RENDER_SWIFT = SWIFT.replace('ofSize: 17, weight: .regular', 'ofSize: 15, weight: .regular')
CORE_SOURCES = {'scripts/sonication_sila2_evidence.py', 'scripts/sonication_sila2_runtime.py',
    'scripts/sonication_sila2_server.py', 'scripts/build_cutrun_input_sonication_sila2.py',
    'scripts/cutrun_input_sonication_control.py', 'scripts/manual_tasks.py',
    'scripts/material_ledger.py', 'interfaces/sila2/standard/provenance.json',
    'model/cutrun-input-sonication-sila2.protocol.json',
    'model/cutrun-input-sonication-sila2.schema.json'}
FALSE_CLAIMS = {'ros_executed': False, 'hardware_executed': False,
    'robot_motion_executed': False, 'instrument_communication_executed': False,
    'biological_acceptance': False, 'complete_cutrun_executed': False}
CREDENTIAL_FORMATS = {'solidcraftbot.sonication-sila-users/1'}
SECRET_KEYS = {'password', 'passwordsha256', 'passwordhash', 'passwordsalt',
               'accesstoken', 'refreshtoken', 'token', 'authorization', 'authorizationtoken', 'privatekey'}


def _output(value):
    path = Path(value).resolve()
    require(path != EVIDENCE.resolve() and path.is_relative_to(EVIDENCE.resolve()),
            'New S09 SiLA evidence must stay under exports/sonication-evidence/<bundle>/')
    return path


def _put(base, name, content, role, files):
    repo_name(name)
    path = _output(base / name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == content, 'Refusing to replace evidence bytes: ' + name)
    else:
        with path.open('xb') as stream:
            stream.write(content)
    files[name] = file_record(path, role, base)
    return name


def _normalized_key(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def _credential_value(value):
    if isinstance(value, dict):
        return any(_normalized_key(key) in SECRET_KEYS
                   or (_normalized_key(key) == 'format' and isinstance(item, str)
                       and item in CREDENTIAL_FORMATS)
                   or _credential_value(item) for key, item in value.items())
    return isinstance(value, list) and any(_credential_value(item) for item in value)


def _credential_bytes(content):
    if b'PRIVATE KEY' in content:
        return True
    text = content.decode('utf-8', errors='replace')
    try:
        if _credential_value(json.loads(text)):
            return True
    except (ValueError, TypeError):
        pass
    # Test logs may contain a JSON fragment or Python-style response rather
    # than one JSON document. Match field assignments, not prose words such
    # as a test description mentioning password handling.
    quoted = re.compile(r'''(["'])([^"'\r\n]{1,128})\1\s*[:=]\s*''')
    for match in quoted.finditer(text):
        key = _normalized_key(match.group(2))
        if key in SECRET_KEYS:
            return True
        if key == 'format':
            value = re.match(r'''["']([^"'\r\n]+)["']''', text[match.end():])
            if value and value.group(1) in CREDENTIAL_FORMATS:
                return True
    for match in re.finditer(
            r'(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_-]{0,80})\s*([:=])\s*\S', text):
        keys = SECRET_KEYS if match.group(2) == '=' else {
            'accesstoken', 'refreshtoken', 'authorization', 'authorizationtoken'}
        if _normalized_key(match.group(1)) in keys:
            return True
    return False


def _public_bytes(path):
    path = Path(path)
    require(path.suffix.lower() not in {'.key', '.p12', '.pfx'}
            and not any(word in path.name.lower() for word in ('credential', 'login', 'secret')),
            'Credentials and private keys must never enter an evidence bundle')
    content = path.read_bytes()
    require(not _credential_bytes(content), 'Credential material is not evidence')
    return content


def _certificate(content, server_uuid):
    # This is the installed server TLS dependency, never an installation step.
    from cryptography import x509
    require(b'PRIVATE KEY' not in content, 'A private key is not public identity')
    try:
        certificate = x509.load_pem_x509_certificate(content)
        identity = certificate.extensions.get_extension_for_oid(
            x509.ObjectIdentifier('1.3.6.1.4.1.58583')).value.value.decode()
    except (ValueError, x509.ExtensionNotFound, UnicodeError) as error:
        raise TaskError('Public SiLA certificate identity is invalid') from error
    require(identity == server_uuid, 'Public certificate belongs to another SiLA server')


def _identity(value, base, files, server_uuid):
    if value is None:
        return None, {}
    if isinstance(value, (str, Path)):
        value = read_json(value)
    require(isinstance(value, dict), 'Explicit public SiLA ready identity required')
    require(not _credential_value(value)
            and not any(_normalized_key(key) in {'credentials', 'users'} for key in value),
            'Credentials must never enter public identity')
    require(value.get('server_uuid') == server_uuid and value.get('tls') is True
            and value.get('bind') in {'127.0.0.1', 'localhost', '::1'}
            and type(value.get('port')) is int and 0 < value['port'] < 65536,
            'Public identity must bind this server to an executed TLS loopback endpoint')
    require(value.get('simulation_only', True) is True and value.get('hardware_available', False) is False,
            'Public S09 endpoint must retain its simulation-only boundary')
    content = _public_bytes(value['certificate'])
    _certificate(content, server_uuid)
    checksum = sha(content)
    require(value.get('certificate_sha256', checksum) == checksum, 'Public certificate checksum mismatch')
    name = _put(base, 'inputs/public/server.crt', content, 'public_tls_certificate', files)
    identity = {key: copy.deepcopy(value[key]) for key in
        ('server_uuid', 'boot_id', 'bind', 'port', 'tls', 'feature') if key in value}
    identity.update(certificate=name, certificate_sha256=checksum,
                    simulation_only=True, hardware_available=False)
    served = {}
    for identifier, path in sorted(value.get('served_feature_xml', {}).items()):
        require(re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', identifier) is not None,
                'Simple delivered feature identifier required')
        served[identifier] = _put(base, 'inputs/served-features/' + identifier + '.sila.xml',
            _public_bytes(path), 'sdk_delivered_feature_xml', files)
    return identity, served


def _source_snapshots(journal, pins, base, files):
    require(isinstance(pins, dict) and pins and all(is_sha(value) for value in pins.values()),
            'Nonempty source closure with SHA-256 pins required')
    result = {}
    for name, checksum in sorted(pins.items()):
        repo_name(name)
        require(not name.startswith('exports/'), 'Runtime credentials are not repository sources')
        content = fixture_evidence._source_bytes(journal, ROOT, name, checksum)
        result[name] = _put(base, 'inputs/sources/' + checksum + '/' + name,
                            content, 'source_snapshot', files)
    return result


def _verify_receipts(events, server_uuid, network_pins):
    previous, loopback = {}, []
    immutable = ('request_id', 'fingerprint', 'command', 'arguments', 'principal',
                 'server_uuid', 'boot_id', 'execution_uuid', 'transport',
                 'accepted_server_time_s', 'confirmation_event_sequence')
    for event in events:
        state = event['state']
        require(state.get('control') == {'mode': 's09_sila2_network/1',
            'server_uuid': server_uuid, 'source_files_sha256': network_pins},
            'Root network binding/source closure changed')
        commands = state.get('network', {}).get('commands')
        require(isinstance(commands, dict) and set(previous) <= set(commands),
                'Durable command receipts disappeared')
        for request_id, record in commands.items():
            require(record.get('request_id') == request_id
                and record.get('server_uuid') == server_uuid
                and record.get('arguments', {}).get('run_identifier') == event['run_id']
                and record['arguments'].get('request_identifier') == request_id
                and record.get('fingerprint') == sha(encoded({'command': record['command'],
                    'arguments': record['arguments']}).encode())
                and record.get('transport') in {'in_process', 'sila2_loopback'}
                and isinstance(record.get('principal'), str) and record['principal'],
                'Network receipt identity, transport or fingerprint mismatch')
            for field in ('accepted_server_time_s', 'confirmation_event_sequence'):
                require(type(record.get(field)) in (int, float) and math.isfinite(record[field]),
                        'Finite command receipt timing/sequence required')
            if request_id in previous:
                require(all(record.get(key) == previous[request_id].get(key) for key in immutable),
                        'An accepted command identity was rewritten')
                if previous[request_id]['status'] != 'accepted':
                    require(record == previous[request_id], 'A terminal command receipt was rewritten')
            else:
                require(record['confirmation_event_sequence'] == event['sequence'],
                        'Command acceptance must share its first Root event')
        receipt = event['payload'].get('network_receipt')
        if event['sequence'] == 1:
            receipt = state.get('creation_receipt', {}).get('network_receipt')
        require(isinstance(receipt, dict), 'Every bound Root event needs its nested network receipt')
        record = commands.get(receipt.get('request_id'))
        require(record is not None and receipt.get('evidence') == 'network_receipt'
                and all(receipt.get(key) == record.get(key) for key in immutable[:8] if key != 'arguments')
                and receipt.get('transport') == record['transport'], 'Root event receipt differs from its durable command')
        require(event['payload'].get('evidence') != 'network_receipt'
                or event['kind'] in {'command_finished', 'execution_interrupted', 'session_closed'},
                'Domain provenance cannot be replaced by transport evidence')
        if 'observation' in event['payload']:
            require(event['payload']['evidence'] == 'test_fixture'
                    and event['payload']['observation']['source_kind'] == 'test_fixture',
                    'Transport cannot upgrade fixture observation provenance')
        stamp = event.get('time_unix_s')
        require(type(stamp) in (int, float) and math.isfinite(stamp), 'Finite actual journal capture time required')
        previous = copy.deepcopy(commands)
    for request_id, record in sorted(previous.items()):
        if record['transport'] == 'sila2_loopback':
            loopback.append({'run_id': events[-1]['run_id'], 'request_id': request_id,
                'execution_uuid': record['execution_uuid'], 'boot_id': record['boot_id'],
                'status': record['status']})
    return loopback


def _verify_effects(events):
    requests, performed, last = {}, {}, {}
    for event in events:
        state = event['state']
        require(set(last) <= set(state['bookings']), 'Canonical material bookings disappeared')
        for identity, booking in state['bookings'].items():
            if identity in requests:
                require(requests[identity] == booking['request'], 'Canonical material intent was rewritten')
            requests[identity] = copy.deepcopy(booking['request'])
            if booking['outcome'] == 'performed':
                effects = {key: booking[key] for key in ('actual_inputs', 'actual_outputs')}
                if identity in performed:
                    require(effects == performed[identity] and last[identity] == 'performed',
                            'A canonical material effect was repeated or rewritten')
                performed[identity] = copy.deepcopy(effects)
            elif identity in performed:
                raise TaskError('A confirmed canonical material effect was undone')
            last[identity] = booking['outcome']
        for identity in state['inventory']['materials']:
            value = remaining(state, identity)['value']
            require(value is None or value >= 0, 'Canonical material balance is negative')
        for identity in fixture_evidence._sonication_actions(state):
            fixture_evidence._intent_view(state, identity)
    return {'canonical_performed_effects': len(performed),
            'sonication_intents': sorted(fixture_evidence._sonication_actions(events[-1]['state']))}


def _verify_domain_report(report, events):
    fixture_evidence._verify_report(report, events)
    for key in ('reference_success', 'preparation_complete', 'preparation_execution_ready',
                'biochemical_protocol_executed', 'authenticated_actor', 'vendor_qc_decoder_executed'):
        require(report.get(key) is False, 'Fixture domain claims cannot be upgraded by network evidence: ' + key)


def _scene(event, index, focus):
    scene = fixture_evidence._scene(event, event['run_id'], None, index, INTERVAL, focus)
    scene.pop('measured_fixture_elapsed_s')
    receipt = event['payload'].get('network_receipt') or event['state'].get('creation_receipt', {}).get('network_receipt')
    scene['capture_times'] = {'journal_time_unix_s': event['time_unix_s'],
        'server_time_s': None if receipt is None else receipt.get('server_time_s'),
        'basis': 'actual recorded capture timestamps; not measured process duration'}
    scene['network_receipt'] = copy.deepcopy(receipt)
    return scene


def scene_text(scene, claims):
    lines = ['Schematische Darstellung | test_fixture',
        'SiLA-Loopback ausgeführt' if claims['network_executed'] else 'SiLA-Loopback nicht nachgewiesen',
        'ROS/Hardware/Roboterbewegung nicht ausgeführt',
        'Run: ' + scene['run_id'] + ' | Ereignis ' + str(scene['event_sequence']) + ': ' + scene['event_kind'],
        'SHA256: ' + scene['event_sha256'],
        'Reaktion: ' + scene['reaction_id'] + ' | Material: ' + scene['material_id'],
        'Gefäß: ' + str(scene['vessel_id']) + ' | Ort: ' + encoded(scene['location']),
        'Restmenge: ' + encoded(scene['remaining']) + ' | Root: ' + scene['root_status'],
        'TestClock/Rootintervall: ' + str(scene['process_time_s']['minimum']) + '..'
            + str(scene['process_time_s']['maximum']) + ' s',
        'Erfassungszeitpunkte (keine Prozessdauer): Journal=' + str(scene['capture_times']['journal_time_unix_s'])
            + '; Server=' + str(scene['capture_times']['server_time_s']),
        'Video: ' + str(scene['video_time_s']) + ' s; 0.5 s/Ereignis, unabhängig gerafft.']
    receipt = scene['network_receipt']
    if receipt:
        lines += ['Netzquittung: ' + receipt['request_id'] + ' | ' + receipt['command']
                  + ' | Principal: ' + receipt['principal'] + ' | Boot: ' + receipt['boot_id']]
    intent = scene['intent']
    if intent is not None:
        lines += ['Absicht: ' + scene['intent_id'] + ' | Stufe: ' + intent['stage_run_id']
                  + ' | Buchung: ' + intent['booking_outcome'],
                  'Pulsplan (fiktiv): n=' + str(intent['pulse_plan']['cycles'])
                      + '; EIN=' + str(intent['pulse_plan']['pulse_on_s']) + ' s; Pause zwischen Pulsen='
                      + str(intent['pulse_plan']['between_pulses_s']) + ' s',
                  'Plan EIN gesamt=' + str(intent['pulse_plan']['total_on_s']) + ' s; nominale Planzeit='
                      + str(intent['pulse_plan']['nominal_elapsed_s']) + ' s; keine Geräteausführung.']
        physical = intent['physical_receipt']
        lines += ['Original Wirkungsbeleg: ' + ('noch keiner' if physical is None else
                   physical['observation']['artifact_sha256'])]
        sizes = intent['size_records']
        lines += ['GRÖSSENPRÜFUNG: WIDERSPRUCH; S09-Abschluss gesperrt.' if any(
            record['fixture_range_conformant'] is not True for record in sizes.values()) else
            'GRÖSSENPRÜFUNG: alle erfassten Fixture-Bereiche passend; weitere Gates separat.' if sizes else
            'GRÖSSENPRÜFUNG: kein Befund; Konzentration ersetzt keine Fragmentgröße.']
        for identity, record in sorted(sizes.items()):
            observation = record['observation']
            lines += ['Größenbefund ' + identity + ': ' + str(observation['minimum_bp']) + '..'
                      + str(observation['maximum_bp']) + ' bp; passend=' + str(record['fixture_range_conformant']),
                      'Original: ' + observation['artifact_sha256'] + '; QC: ' + observation['withdrawal_intent_id']]
    else:
        lines += ['Noch keine Sonikationsabsicht; keine Wirkung angenommen.']
    for stage_id, phases in sorted(scene['phase_evidence'].items()):
        for phase_id, records in sorted(phases.items()):
            for record in records['times']:
                lines += ['Zeitbeleg ' + record['evidence_id'] + ': '
                    + str(record['start_earliest_s']) + '..' + str(record['start_latest_s']) + ' bis '
                    + str(record['end_earliest_s']) + '..' + str(record['end_latest_s']) + ' s',
                    'Original: ' + record['artifact_sha256']]
            for record in records['temperatures']:
                lines += ['Temperaturbeleg ' + record['evidence_id'] + ': '
                    + str(record['minimum_deg_c']) + '..' + str(record['maximum_deg_c']) + ' °C; Unsicherheit='
                    + str(record['uncertainty_deg_c']) + ' °C', 'Original: ' + record['artifact_sha256']]
    lines += ['S09-Abschluss ist kein CUT&RUN-Gesamtabschluss; keine Gerätequalifikation.']
    return '\n'.join(lines)


def _claims(loopback, identity, logs):
    executed = bool(loopback and identity is not None and logs)
    return {'network_executed': executed, 'sila_executed': executed, **FALSE_CLAIMS,
        'test_fixture_only': True, 'visually_reviewed': False,
        'scope': 'TLS loopback Root control only' if executed else 'offline Root evidence; loopback unqualified',
        'time_axes': {'process': 'logical Root/TestClock interval',
            'capture': 'actual server/journal event timestamps, not process duration',
            'video': 'independent presentation clock', 'video_event_interval_s': INTERVAL}}


def _fdl_identifier(content):
    root = ET.fromstring(content)
    return root.findtext('{http://www.sila-standard.org}Identifier')


def _verify_custom_fdl(content, profile):
    root = ET.fromstring(content)
    q = lambda name: '{http://www.sila-standard.org}' + name
    feature = profile['feature']
    require(root.tag == q('Feature') and root.get('FeatureVersion') == feature['version']
            and root.get('SiLA2Version') == feature['sila_version']
            and root.get('Originator') == feature['originator'] and root.get('Category') == feature['category']
            and root.findtext(q('Identifier')) == feature['identifier'], 'Generated FDL header differs from its contract')
    commands = root.findall(q('Command'))
    require(len(commands) == len(profile['commands']), 'Generated FDL command count differs from contract')
    for node, source in zip(commands, profile['commands']):
        parameters = [(item.findtext(q('Identifier')), item.findtext(q('DataType') + '/' + q('Basic')))
                      for item in node.findall(q('Parameter'))]
        expected = [(contract.camel(field['name']), {'string': 'String', 'bool': 'Boolean'}[field['type']])
                    for field in source['arguments']]
        require(node.findtext(q('Identifier')) == source['name'] and parameters == expected
                and node.findtext(q('Observable')) == ('Yes' if source['observable'] else 'No'),
                'Generated FDL command surface differs from its source contract')


def export_bundle(runtime, directory, *, run_ids=None, public_identity=None, test_logs=None, render=False):
    """Snapshot a new bundle without modifying the Root, credentials or old media."""
    base = _output(directory)
    require(not base.exists(), 'Evidence bundle already exists; choose a new directory')
    files, runs = {}, []
    pins = copy.deepcopy(runtime.profile['source_files_sha256'])
    require(CORE_SOURCES <= set(pins), 'Missing S09 network implementation source closure')
    contract.verify_source_files(pins)
    base.mkdir(parents=True, exist_ok=False)
    with Journal(runtime.journal_path) as journal:
        selected = ([row[0] for row in journal.connection.execute('SELECT id FROM runs ORDER BY id')]
                    if run_ids is None else list(run_ids))
        require(selected and len(selected) == len(set(selected)), 'Unique existing Root run identities required')
        snapshots = _source_snapshots(journal, pins, base, files)
        for index, run_id in enumerate(selected, 1):
            name = fixture_evidence._raw_export(journal, run_id, base, '%03d' % index, files)
            unused, events, artifacts = verify_journal(base / name)
            report = runtime.report(run_id)
            _verify_domain_report(report, events)
            _verify_receipts(events, runtime.server_uuid, pins)
            _verify_effects(events)
            report_name = _put(base, 'inputs/report-%03d.json' % index, json_bytes(report), 'root_report', files)
            domain_pins = events[-1]['state']['definition']['source_files_sha256']
            runs.append({'run_id': run_id, 'journal': name, 'report': report_name,
                'source_files_sha256': domain_pins,
                'source_snapshots': _source_snapshots(journal, domain_pins, base, files)})
    identity, served = _identity(public_identity, base, files, runtime.server_uuid)
    logs = {}
    for label, path in sorted((test_logs or {}).items()):
        require(isinstance(label, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', label) is not None,
                'Safe explicit test-log identity required')
        content = _public_bytes(path)
        require(content.strip(), 'Nonempty test log required')
        logs[label] = _put(base, 'inputs/test-logs/' + label + '.log', content, 'test_log', files)
    profile_name = _put(base, 'inputs/network-profile.json', json_bytes(runtime.profile), 'network_profile', files)
    fdl = _put(base, 'inputs/generated/CutRunInputSonicationWorkflow-v1_0.sila.xml',
               contract.feature(runtime.profile).encode(), 'generated_custom_fdl', files)
    manifest = {'format': FORMAT, 'server_uuid': runtime.server_uuid, 'boot_id': runtime.boot_id,
        'profile': profile_name, 'source_files_sha256': pins, 'source_snapshots': snapshots,
        'generated_fdl': fdl, 'served_feature_xml': served, 'public_identity': identity,
        'test_logs': logs, 'runs': runs, 'scenes': 'scenes.json', 'cards': 'scene-cards.json',
        'render': None, 'files': sorted(files.values(), key=lambda item: item['path'])}
    derived = _derive(base, manifest)
    manifest['claims'], manifest['loopback_evidence'] = derived['claims'], derived['loopback_evidence']
    _put(base, manifest['scenes'], json_bytes(derived['scenes']), 'journal_derived_scenes', files)
    _put(base, manifest['cards'], json_bytes(derived['cards']), 'schematic_cards', files)
    if render:
        manifest['render'] = _render(base, derived['cards'], files)
    manifest['files'] = sorted(files.values(), key=lambda item: item['path'])
    path = base / 'manifest.json'
    with path.open('xb') as stream:
        stream.write(json_bytes(manifest))
    check_manifest(path)
    return path


def _derive(base, manifest):
    files = fixture_evidence._verify_records(base, manifest['files'])
    def listed(name):
        require(name in files, 'Referenced evidence file is not byte-pinned: ' + str(name))
        return relative_file(base, name)
    pins = manifest['source_files_sha256']
    require(CORE_SOURCES <= set(pins) and set(manifest['source_snapshots']) == set(pins),
            'Incomplete S09 network source closure')
    for name, checksum in pins.items():
        repo_name(name)
        require(is_sha(checksum) and sha(listed(manifest['source_snapshots'][name]).read_bytes()) == checksum,
                'Archived network source checksum mismatch: ' + name)
    profile = read_json(listed(manifest['profile']))
    require(profile['source_files_sha256'] == pins, 'Network profile source closure differs from Root binding')
    source_contract = read_json(listed(manifest['source_snapshots'][
        'model/cutrun-input-sonication-sila2.protocol.json']))
    require(all(profile.get(key) == value for key, value in source_contract.items()),
            'Archived network profile differs from its original contract')
    require(set(profile['runtime_sources']) <= set(pins), 'Runtime source entry omitted from closure')
    provenance = read_json(listed(manifest['source_snapshots']['interfaces/sila2/standard/provenance.json']))
    require(profile['standard_features'] == provenance['files'], 'Standard FDL provenance changed')
    for reference in profile['standard_features']:
        require(pins.get(reference['source']) == reference['source_sha256'], 'Standard FDL source pin changed')
    generated = listed(manifest['generated_fdl']).read_bytes()
    _verify_custom_fdl(generated, profile)
    identifiers = {profile['feature']['identifier'], *(item['identifier'] for item in profile['standard_features'])}
    for identifier, name in manifest['served_feature_xml'].items():
        require(identifier in identifiers and _fdl_identifier(listed(name).read_bytes()) == identifier,
                'SDK-delivered FDL identity differs from its recorded feature')
    identity = manifest['public_identity']
    if identity is not None:
        require(identity.get('server_uuid') == manifest['server_uuid'] and identity.get('tls') is True
                and identity.get('bind') in {'127.0.0.1', 'localhost', '::1'}
                and type(identity.get('port')) is int and 0 < identity['port'] < 65536,
                'Public TLS loopback identity changed')
        cert = listed(identity['certificate']).read_bytes()
        require(sha(cert) == identity['certificate_sha256'], 'Public certificate checksum mismatch')
        _certificate(cert, manifest['server_uuid'])
    for name in manifest['test_logs'].values():
        require(listed(name).read_bytes().strip(), 'Empty test log cannot qualify loopback evidence')
    scenes, summaries, loopback, ids = [], [], [], set()
    for item in manifest['runs']:
        require(item['run_id'] not in ids, 'Root run repeated in evidence bundle')
        ids.add(item['run_id'])
        exported, events, artifacts = verify_journal(listed(item['journal']))
        require(exported['run_id'] == item['run_id'], 'Run identity differs from original journal')
        for path in artifacts.values():
            listed(str(path.relative_to(base)))
        report = read_json(listed(item['report']))
        _verify_domain_report(report, events)
        state = events[-1]['state']
        require(report.get('transport_receipts', {}).get('control') == state['control']
                and report['transport_receipts'].get('network') == state['network'],
                'Report transport receipts differ from committed Root state')
        expected_loopback = any(record['transport'] == 'sila2_loopback'
                                for record in state['network']['commands'].values())
        require(report['transport_receipts'].get('sila_loopback_executed') is expected_loopback,
                'Report loopback receipt claim differs from Root')
        loopback.extend(_verify_receipts(events, manifest['server_uuid'], pins))
        effects = _verify_effects(events)
        domain_pins = state['definition']['source_files_sha256']
        require(item['source_files_sha256'] == domain_pins and set(item['source_snapshots']) == set(domain_pins),
                'Incomplete domain source closure')
        for name, checksum in domain_pins.items():
            require(sha(listed(item['source_snapshots'][name]).read_bytes()) == checksum,
                    'Archived domain source checksum mismatch: ' + name)
        focus = None
        for event in events:
            actions = fixture_evidence._sonication_actions(event['state'])
            if focus is None and actions:
                focus = sorted(actions)[0]
            scenes.append(_scene(event, len(scenes), focus))
        summaries.append({'run_id': item['run_id'], 'chain_head_sha256': exported['chain_head_sha256'],
                          'event_count': len(events), 'root_status': state['status'], **effects})
    require(scenes, 'Existing Root journal events required')
    if loopback and identity is not None and identity.get('boot_id') is not None:
        require(identity['boot_id'] in {record['boot_id'] for record in loopback},
                'Public ready boot does not match any archived loopback receipt')
    claims = _claims(loopback, identity, manifest['test_logs'])
    binding = {'receipts': loopback, 'public_server_uuid': None if identity is None else identity['server_uuid'],
        'certificate_sha256': None if identity is None else identity['certificate_sha256'],
        'test_log_sha256': {label: files[name]['sha256'] for label, name in manifest['test_logs'].items()},
        'runs': summaries, 'authentication_limit': 'integrity hashes, not signed or independently authenticated audit evidence'}
    cards = [{'title': 'S09 / TLS-Loopback | Schematische Darstellung',
              'body': scene_text(scene, claims), 'png': '%06d.png' % index}
             for index, scene in enumerate(scenes, 1)]
    return {'claims': claims, 'loopback_evidence': binding, 'scenes': scenes, 'cards': cards}


def _render(base, cards, files):
    tools = versions()
    frames = base / 'frames'
    frames.mkdir(exist_ok=False)
    source = _put(base, 'renderer.swift', RENDER_SWIFT.encode(), 'schematic_renderer_source', files)
    _put(base, 'tool-versions.json', json_bytes(tools), 'tool_versions', files)
    for index, card in enumerate(cards, 1):
        _put(base, 'frames/%06d.txt' % index, card['body'].encode(), 'schematic_scene_text', files)
    binary = base / 'renderer-appkit'
    with tempfile.TemporaryDirectory(prefix='s09-swift-cache-', dir=ROOT / 'exports') as cache:
        env = {**os.environ, 'CLANG_MODULE_CACHE_PATH': cache, 'SWIFT_MODULECACHE_PATH': cache}
        run([tools['tools']['swiftc'], '-module-cache-path', cache, str(base / source), '-o', str(binary)], env=env)
        run([str(binary), str(base / 'scene-cards.json'), str(frames)], env=env)
    files[binary.name] = file_record(binary, 'compiled_schematic_renderer', base)
    for index in range(1, len(cards) + 1):
        name = 'frames/%06d.png' % index
        files[name] = file_record(base / name, 'schematic_png', base)
    video = base / 's09-sila2-evidence.mp4'
    run([tools['tools']['ffmpeg'], '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
         '-framerate', '2', '-i', str(frames / '%06d.png'), '-c:v', 'libx264',
         '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)])
    files[video.name] = file_record(video, 'schematic_video', base)
    stream = probe_video(video)
    return {'width': WIDTH, 'height': HEIGHT, 'frame_count': len(cards), 'seconds_per_event': INTERVAL,
        'video': video.name, 'video_duration_s': float(stream['duration']), 'video_codec': stream['codec_name'],
        'renderer_source': source, 'renderer_binary': binary.name, 'tool_versions': 'tool-versions.json',
        'visual_review': {'reviewed': False, 'frames': fixture_evidence.inspection_frames(len(cards)), 'record': None}}


def check_manifest(path):
    """Verify archived bytes and rederive claims without consulting live sources."""
    path = _output(path)
    manifest = read_json(path)
    require(manifest.get('format') == FORMAT, 'Versioned S09 SiLA evidence manifest required')
    require(set(manifest) == {'format', 'server_uuid', 'boot_id', 'profile', 'source_files_sha256',
        'source_snapshots', 'generated_fdl', 'served_feature_xml', 'public_identity', 'test_logs',
        'runs', 'scenes', 'cards', 'render', 'files', 'claims', 'loopback_evidence'},
        'Unexpected S09 evidence manifest fields')
    base = path.parent
    derived = _derive(base, manifest)
    require(manifest['claims'] == derived['claims']
            and manifest['loopback_evidence'] == derived['loopback_evidence'],
            'Network, timing, fixture or canonical effect claims differ from archived Root evidence')
    records = {item['path']: item for item in manifest['files']}
    for name, expected in [(manifest['scenes'], derived['scenes']), (manifest['cards'], derived['cards'])]:
        require(name in records and read_json(relative_file(base, name)) == expected,
                'Schematic scenes differ from original journal events')
    rendered = manifest['render']
    if rendered is not None:
        count = len(derived['cards'])
        require(rendered['width'] == WIDTH and rendered['height'] == HEIGHT
                and rendered['frame_count'] == count and rendered['seconds_per_event'] == INTERVAL
                and rendered['visual_review'] == {'reviewed': False,
                    'frames': fixture_evidence.inspection_frames(count), 'record': None},
                'Unreviewed schematic render metadata changed')
        for key in ('video', 'renderer_source', 'renderer_binary', 'tool_versions'):
            require(rendered[key] in records, 'Rendered artifact lacks its byte pin')
        for index, card in enumerate(derived['cards'], 1):
            name = 'frames/%06d.txt' % index
            png = 'frames/%06d.png' % index
            require(name in records and relative_file(base, name).read_bytes() == card['body'].encode()
                    and png in records, 'Rendered scene text or image missing')
            content = relative_file(base, png).read_bytes()
            require(content[:8] == b'\x89PNG\r\n\x1a\n'
                    and int.from_bytes(content[16:20], 'big') == WIDTH
                    and int.from_bytes(content[20:24], 'big') == HEIGHT, 'Encoded PNG dimensions mismatch')
        stream = probe_video(relative_file(base, rendered['video']))
        require(stream['codec_name'] == rendered['video_codec'] == 'h264'
                and int(stream['width']) == WIDTH and int(stream['height']) == HEIGHT
                and int(stream['nb_frames']) == count
                and abs(float(stream['duration']) - count * INTERVAL) < 0.01
                and abs(rendered['video_duration_s'] - count * INTERVAL) < 0.01,
                'Encoded video differs from event count, dimensions or independent presentation clock')
    actual = {str(candidate.relative_to(base)) for candidate in base.rglob('*') if candidate.is_file()}
    require(actual == set(records) | {path.name}, 'Evidence byte inventory omits or invents a file')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_manifest(args.check)
        print(json.dumps({'checked': True, 'format': FORMAT, 'claims': result['claims']}))
        return 0
    except (TaskError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
