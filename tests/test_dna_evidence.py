"""Private offline fixtures test evidence verification; they prove no network run."""
import copy
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from dna_evidence_manifest import (EVIDENCE, INPUT_FORMAT, TRANSPORT_FORMAT, check_manifest,
    derive, export_journal, output_path, read_json, sha, verify_journal, write_json)
from dna_quantification_ledger import classify_input, remaining
from dna_quantification_tasks import load_contract
from build_dna_ros_interfaces import build as build_ros_interfaces
from manual_tasks import Journal, TaskError
from render_dna_evidence import render, scene_text


class DnaEvidenceTests(unittest.TestCase):
    def setUp(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='unit-evidence-', dir=EVIDENCE)
        self.folder = Path(self.temp.name)
        self.inputs = self.folder / 'inputs'
        self.inputs.mkdir()
        source = 'model/dna-quantification.protocol.json'
        protocol = read_json(ROOT / source)
        self.source_pins = {source: sha((ROOT / source).read_bytes())}
        for relative in [load_contract()['source_path'], 'scripts/build_dna_ros_interfaces.py',
                         'scripts/dna_quantification_tasks.py']:
            self.source_pins[relative] = sha((ROOT / relative).read_bytes())
        self.journal = Journal(self.inputs / 'unit.sqlite3')
        original = {'id': 'UNIT.Original', 'kind': 'original', 'sample_id': 'DNA01',
                    'initial_volume_ul': 40, 'content_revision': 0,
                    'home': {'kind': 'rack', 'rack_id': 'UNIT.Rack', 'place_id': 'Slot01'},
                    'location': {'kind': 'rack', 'rack_id': 'UNIT.Rack', 'place_id': 'Slot01'}}
        self.state = {'run_id': 'UNIT.EVIDENCE', 'status': 'running', 'resources': [],
                      'definition': {'source_files_sha256': self.source_pins, 'protocol': protocol},
                      'logical_time_s': 0, 'samples': {}, 'attempts': {}, 'contexts': {},
                      'bookings': {}, 'dilutions': {}, 'pending_dilution': None,
                      'active_attempt_id': None, 'active_context_id': None,
                      'recovery_required': None, 'inventory': {'vessels': {original['id']: original}}}
        self.state.update(control={'mode': 'sila2_network/1', 'server_uuid': 'UNIT.SERVER'},
                          network={'commands': {}})
        self.state['control']['source_files_sha256'] = copy.deepcopy(self.source_pins)
        self.journal.create(self.state['run_id'], self.state, immutable_definition=True)
        self.receipts = []
        for index, factor in enumerate([10, 20], 1):
            self.add_pair(index, factor)
        self.state['status'] = 'completed'
        self.state['task_port'] = {'goals': {'UNIT.Goal': {'evidence': 'worker_claim'}}}
        self.state['active_attempt_id'] = self.state['active_context_id'] = None
        self.append('run_completed', {})
        export_journal(self.journal, self.state['run_id'], self.inputs)
        report = {key: copy.deepcopy(self.state[key]) for key in ['run_id', 'status', 'logical_time_s',
            'samples', 'attempts', 'contexts', 'bookings', 'dilutions', 'pending_dilution',
            'resources', 'recovery_required', 'inventory']}
        report.update(source_files_sha256=self.source_pins, worker='MockWorker',
                      network_executed=True, hardware_executed=False, robot_motion_executed=False,
                      passed=True, control=copy.deepcopy(self.state['control']),
                      network=copy.deepcopy(self.state['network']),
                      task_port=copy.deepcopy(self.state['task_port']))
        for identity, vessel in report['inventory']['vessels'].items():
            vessel['remaining_volume_ul'] = remaining(self.state, identity)
        write_json(self.inputs / 'report.json', report)
        write_json(self.inputs / 'transport.json', {
            'format': TRANSPORT_FORMAT, 'transport': 'SiLA2/TLS/gRPC', 'host': '127.0.0.1',
            'network_executed': True,
            'server': {'server_uuid': 'UNIT.SERVER', 'boot_ids': ['UNIT.BOOT'],
                       'tls_certificate_sha256': 'a' * 64},
            'receipts': self.receipts})
        (self.inputs / 'unit-tests.log').write_text('Private offline unit fixture; no network execution proof.\n')
        fdl = self.inputs / 'UnitFeature.sila.xml'
        fdl.write_text('<Feature Identifier="UnitFixture"/>\n')
        self.input = self.folder / 'evidence-input.json'
        write_json(self.input, {'format': INPUT_FORMAT, 'commit': 'a' * 40,
            'working_tree_dirty': True, 'source_files_sha256': self.source_pins,
            'fdl_files_sha256': {str(fdl.relative_to(ROOT)): sha(fdl.read_bytes())},
            'report': 'inputs/report.json', 'journal_export': 'inputs/journal.json',
            'transport': 'inputs/transport.json', 'test_logs': ['inputs/unit-tests.log']})

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def append(self, kind, payload, artifact=None):
        self.journal.append(self.state['run_id'], len(self.journal.history(self.state['run_id'])),
                            kind, payload, self.state, artifact=artifact)

    def add_pair(self, index, factor):
        attempt_id = 'UNIT.A' + str(index)
        stock_id = attempt_id + '.Stock'
        home = {'kind': 'rack', 'rack_id': 'UNIT.Dilutions', 'place_id': 'Slot' + str(index)}
        self.state['inventory']['vessels'][stock_id] = {
            'id': stock_id, 'kind': 'dilution', 'sample_id': 'DNA01',
            'initial_volume_ul': 2 * factor, 'content_revision': 0, 'home': home, 'location': home}
        self.state['bookings'][attempt_id + '.dilution'] = {
            'source_vessel_id': 'UNIT.Original', 'outcome': 'performed', 'actual_volume_ul': 2}
        attempt = {'sample_id': 'DNA01', 'input_vessel_id': stock_id, 'external_factor': factor,
                   'contexts': {}, 'evaluations': {}, 'results': {}}
        self.state['attempts'][attempt_id] = attempt
        self.state['active_attempt_id'] = attempt_id
        for device, value in [('nanodrop', 50), ('qubit', 48)]:
            context_id = attempt_id + '.' + device
            raw = ('UNIT fixture,not a device export,' + context_id + '\n').encode()
            checksum = sha(raw)
            measurement_id, preparation_id = context_id + '.M', context_id + '.P'
            selected = value / factor
            metric = lambda value: {'value': value, 'unit': 'ng/uL', 'source_basis': 'unit_fixture'}
            result = {'artifact_sha256': checksum, 'measurement_id': measurement_id,
                      'preparation_id': preparation_id, 'instrument_messages': {},
                      'metrics': ({'concentration': metric(selected), 'factor': {'value': 50}}
                                  if device == 'nanodrop' else {
                                      'tube_concentration': metric(selected * 2 / 200),
                                      'original_concentration': metric(selected)})}
            local = {'status': 'completed', 'imports': {checksum: {'status': 'accepted'}},
                     'measurements': {measurement_id: {'withdrawn_volume': {'value': 1.5, 'unit': 'uL'}}},
                     'preparations': {preparation_id: {'sample_volume_ul': 2, 'assay_total_volume_ul': 200}}}
            self.state['contexts'][context_id] = {'device': device, 'source_vessel_id': stock_id,
                                                 'attempt_id': attempt_id, 'local': local}
            attempt['contexts'][device] = context_id
            attempt['results'][device] = result
            attempt['evaluations'][device] = classify_input(result, device,
                self.state['definition']['protocol']['assays'][device],
                sample_volume_ul=1.5 if device == 'nanodrop' else 2,
                total_volume_ul=200 if device == 'qubit' else None, external_factor=factor)
            self.state['bookings'][context_id] = {'source_vessel_id': stock_id,
                'outcome': 'performed', 'actual_volume_ul': 1.5 if device == 'nanodrop' else 2}
            self.state['active_context_id'] = context_id
            self.state['logical_time_s'] += 120
            payload = {'command': 'UNIT.Observe', 'status': 'completed', 'request_id': context_id + '.R',
                       'execution_uuid': context_id + '.E', 'principal': 'UNIT.Principal',
                       'server_uuid': 'UNIT.SERVER', 'boot_id': 'UNIT.BOOT',
                       'transport': 'sila2_tls_loopback', 'evidence': 'network_receipt',
                       'server_time_s': 1000 + len(self.receipts) * 3}
            self.state['network']['commands'][payload['request_id']] = {
                key: payload[key] for key in ['command', 'status', 'principal', 'server_uuid',
                                              'boot_id', 'execution_uuid', 'transport']}
            self.append('command_finished', payload, artifact=raw)
            event = self.journal.history(self.state['run_id'])[-1]
            self.receipts.append({'event_sequence': event['sequence'], 'event_sha256': event['sha256'],
                                  'run_id': self.state['run_id'], 'attempt_id': attempt_id,
                                  'context_id': context_id, **payload})

    def test_raw_documents_chain_definition_and_four_original_artifacts_roundtrip(self):
        exported, events, artifacts, _ = verify_journal(self.inputs / 'journal.json')
        self.assertEqual(exported['chain_head_sha256'], self.journal.history(self.state['run_id'])[-1]['sha256'])
        self.assertEqual(len(events), 6)
        self.assertEqual(len(artifacts), 5)  # one definition and four imports
        for row in exported['events']:
            self.assertEqual(sha(row['document'].encode()), row['sha256'])
        self.assertIn('definition', events[-1]['state'])
        self.assertNotIn('definition', json.loads(exported['events'][-1]['document'])['state'])
        with self.assertRaisesRegex(TaskError, 'replace an exported journal'):
            export_journal(self.journal, self.state['run_id'], self.inputs)

    def test_semantics_recompute_both_factors_and_keep_three_time_axes_distinct(self):
        result = derive(self.input)
        self.assertEqual([item['external_factor'] for item in result['attempts']], [10, 20])
        for attempt in result['attempts']:
            self.assertEqual(attempt['devices']['nanodrop']['evaluation']['root_original_concentration']['value'], 50)
            self.assertEqual(attempt['devices']['qubit']['evaluation']['root_original_concentration']['value'], 48)
        final = result['scenes'][-1]
        self.assertEqual((final['logical_time_s'], final['server_elapsed_s'], final['video_time_s']), (480, 9, 2.5))
        self.assertIsNone(final['attempt_id'])
        self.assertIsNone(final['context_id'])
        self.assertIsNone(final['source_vessel_id'])
        self.assertEqual(final['last_completed_reference']['context_id'], 'UNIT.A2.qubit')
        final_text = scene_text(final, result['claims'])
        self.assertIn('kein aktiver Bezug; zuletzt abgeschlossen: UNIT.A2.qubit', final_text)
        self.assertIn('Original-Inventar: UNIT.Original → UNIT.Rack/Slot01', final_text)
        self.assertIn('Original-Heimat: UNIT.Original → UNIT.Rack/Slot01', final_text)
        initial_text = scene_text(result['scenes'][0], result['claims'])
        self.assertIn('noch kein aktiver oder abgeschlossener Bezug', initial_text)
        self.assertIn('Original-Inventar: UNIT.Original → UNIT.Rack/Slot01', initial_text)
        self.assertFalse(result['claims']['ros_executed'])
        self.assertFalse(result['claims']['hardware_executed'])
        text = scene_text(result['scenes'][-2], result['claims'])
        for label in result['claims']['labels']:
            self.assertIn(label, text)
        self.assertIn('keine qualifizierte LLOQ', text)
        self.assertIn('0.1–120 ng', text)
        self.assertIn('F=10', text)
        self.assertIn('F=20', text)
        self.assertIn('Ereignisweise gerafft: 0.5 s/Ereignis', text)

    def test_generated_ros_flag_requires_complete_source_bound_uncompiled_archive(self):
        package = self.inputs / 'ros-interfaces'
        build_ros_interfaces(package)
        report_path = self.inputs / 'report.json'
        report = read_json(report_path)
        report.update(ros_interface_generated=True, ros_compiled=False, ros_executed=False)
        write_json(report_path, report)
        with self.assertRaisesRegex(TaskError, 'requires its archived package'):
            derive(self.input)
        data = read_json(self.input)
        data['ros_interfaces'] = {'report': 'inputs/ros-interfaces/transport-contract.json',
                                  'package_directory': 'inputs/ros-interfaces'}
        write_json(self.input, data)
        result = derive(self.input)
        self.assertTrue(result['claims']['ros_interface_generated'])
        self.assertFalse(result['ros_interfaces']['ros_compiled'])
        self.assertFalse(result['ros_interfaces']['ros_executed'])
        action = package / 'action' / (result['ros_interfaces']['action'] + '.action')
        original = action.read_bytes()
        action.write_bytes(original + b'# altered\n')
        with self.assertRaisesRegex(TaskError, 'ROS artifact checksum'):
            derive(self.input)
        action.write_bytes(original)
        path = package / 'transport-contract.json'
        original_report = read_json(path)
        for field in ['generator_sha256', 'decoder_sha256', 'source_sha256']:
            with self.subTest(field=field):
                changed = copy.deepcopy(original_report)
                changed[field] = '0' * 64
                write_json(path, changed)
                with self.assertRaises(TaskError): derive(self.input)
        write_json(path, original_report)
        changed = copy.deepcopy(original_report)
        changed['runtime']['ros2_executed'] = True
        write_json(path, changed)
        with self.assertRaisesRegex(TaskError, 'do not establish ROS'):
            derive(self.input)

    def test_mutated_raw_artifact_fails_before_render(self):
        exported = read_json(self.inputs / 'journal.json')
        artifact = next(iter(exported['artifacts'].values()))
        with (self.inputs / artifact).open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(TaskError, 'artifact checksum'):
            derive(self.input)

    def test_mutated_journal_document_or_head_fails_even_when_valid_json(self):
        path = self.inputs / 'journal.json'
        original = read_json(path)
        changed = copy.deepcopy(original)
        event = json.loads(changed['events'][1]['document'])
        event['kind'] = 'invented-event'
        changed['events'][1]['document'] = json.dumps(event)
        write_json(path, changed)
        with self.assertRaisesRegex(TaskError, 'document checksum'):
            derive(self.input)
        original['chain_head_sha256'] = '0' * 64
        write_json(path, original)
        with self.assertRaisesRegex(TaskError, 'chain head'):
            derive(self.input)

    def test_report_cannot_rewrite_balance_or_original_result(self):
        path = self.inputs / 'report.json'
        original = read_json(path)
        changed = copy.deepcopy(original)
        changed['inventory']['vessels']['UNIT.Original']['remaining_volume_ul'] = 40
        write_json(path, changed)
        with self.assertRaisesRegex(TaskError, 'canonical ledger'):
            derive(self.input)
        changed = copy.deepcopy(original)
        changed['attempts']['UNIT.A1']['evaluations']['qubit']['root_original_concentration']['value'] = 480
        write_json(path, changed)
        with self.assertRaisesRegex(TaskError, 'differs from journal'):
            derive(self.input)

    def test_transport_requires_exact_journal_receipts_and_public_loopback_identity(self):
        path = self.inputs / 'transport.json'
        original = read_json(path)
        cases = ['host', 'certificate', 'event_hash', 'server_time', 'private_key',
                 'not_executed', 'omitted_receipt']
        for case in cases:
            with self.subTest(case=case):
                changed = copy.deepcopy(original)
                if case == 'host': changed['host'] = '192.0.2.1'
                elif case == 'certificate': changed['server']['tls_certificate_sha256'] = None
                elif case == 'event_hash': changed['receipts'][0]['event_sha256'] = '0' * 64
                elif case == 'server_time': changed['receipts'][0]['server_time_s'] += 1
                elif case == 'private_key': changed['server']['private_key'] = 'never-export'
                elif case == 'not_executed': changed['network_executed'] = False
                else: changed['receipts'].pop()
                write_json(path, changed)
                with self.assertRaises(TaskError): derive(self.input)
        write_json(path, original)

    def test_failed_and_interrupted_tls_completions_are_counted_without_success_invention(self):
        for offset, status in enumerate(['failed', 'interrupted'], 1):
            payload = {'command': 'UNIT.StopOrReject', 'status': status,
                       'request_id': 'UNIT.' + status, 'execution_uuid': 'UNIT.Execution.' + status,
                       'principal': 'UNIT.Principal', 'server_uuid': 'UNIT.SERVER',
                       'boot_id': 'UNIT.BOOT', 'transport': 'sila2_tls_loopback',
                       'evidence': 'network_receipt', 'server_time_s': 1009 + offset * 3}
            self.state['network']['commands'][payload['request_id']] = {
                key: payload[key] for key in ['command', 'status', 'principal', 'server_uuid',
                                              'boot_id', 'execution_uuid', 'transport']}
            self.append('command_finished', payload)
            event = self.journal.history(self.state['run_id'])[-1]
            self.receipts.append({'event_sequence': event['sequence'], 'event_sha256': event['sha256'],
                                  'run_id': self.state['run_id'], **payload})
            folder = self.folder / status
            export_journal(self.journal, self.state['run_id'], folder)
            report = read_json(self.inputs / 'report.json')
            report['network'] = copy.deepcopy(self.state['network'])
            write_json(self.inputs / 'report.json', report)
            transport = read_json(self.inputs / 'transport.json')
            transport['receipts'] = self.receipts
            write_json(self.inputs / 'transport.json', transport)
            data = read_json(self.input)
            data['journal_export'] = status + '/journal.json'
            write_json(self.input, data)
            result = derive(self.input)
            self.assertEqual(result['claims']['network_command_outcomes']['completed'], 4)
            self.assertEqual(result['claims']['network_command_outcomes'][status], 1)
            self.assertEqual(result['scenes'][-1]['command_status'], status)

    def test_changed_source_or_fdl_pin_and_output_escape_are_rejected(self):
        data = read_json(self.input)
        key = next(iter(data['fdl_files_sha256']))
        data['fdl_files_sha256'][key] = '0' * 64
        write_json(self.input, data)
        with self.assertRaisesRegex(TaskError, 'Changed source/FDL pin'):
            derive(self.input)
        for path in [ROOT / 'docs/media/new.png', ROOT / 'exports/other/manifest.json', EVIDENCE]:
            with self.subTest(path=path), self.assertRaises(TaskError):
                output_path(path)

    @unittest.skipUnless(all(shutil.which(tool) for tool in ['swiftc', 'ffmpeg', 'ffprobe']),
                         'Native schematic renderer needs installed AppKit/Swift and FFmpeg')
    def test_render_check_and_byte_semantic_or_missing_output_mutations(self):
        manifest_path = render(self.input)
        original = read_json(manifest_path)
        self.assertEqual(original['render']['frame_count'], 6)
        self.assertEqual(original['render']['video_duration_s'], 3)
        self.assertEqual(check_manifest(manifest_path)['claims']['network_scope'], 'TLS/gRPC loopback only')
        frame = self.folder / 'frames/000001.png'
        content = frame.read_bytes()
        self.assertEqual(struct.unpack('>II', content[16:24]), (1600, 1000))
        frame.write_bytes(content + b'mutated')
        with self.assertRaisesRegex(TaskError, 'byte checksum'):
            check_manifest(manifest_path)
        frame.write_bytes(content)
        changed = copy.deepcopy(original)
        changed['claims']['hardware_executed'] = True
        write_json(manifest_path, changed)
        with self.assertRaisesRegex(TaskError, 'semantic claim'):
            check_manifest(manifest_path)
        changed = copy.deepcopy(original)
        changed['files'] = [item for item in changed['files'] if item['role'] != 'scene_png']
        write_json(manifest_path, changed)
        with self.assertRaisesRegex(TaskError, 'Missing rendered scene'):
            check_manifest(manifest_path)
        write_json(manifest_path, original)
        self.assertEqual(check_manifest(manifest_path)['journal']['event_count'], 6)


if __name__ == '__main__':
    unittest.main()
