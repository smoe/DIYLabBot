"""Disposable offline archives cannot upgrade Root fixtures into network proof."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from manual_tasks import Journal, TaskError
from sonication_sila2_runtime import SonicationRuntime
import sonication_sila2_evidence as evidence


class PublicEvidenceCredentialFilterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='s09-public-evidence-private-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def source(self, content, name='disposable-test.log'):
        path = self.directory / name
        path.write_bytes(content)
        return path

    def test_users_json_is_rejected_by_credential_format_and_hash_fields_not_filename(self):
        fake = {'format': 'solidcraftbot.sonication-sila-users/1', 'users': [{
            'username': 'disposable-unit-test-user', 'role': 'operator', 'salt': 'f00d' * 8,
            'iterations': 200000, 'password_sha256': 'deadbeef' * 8}]}
        path = self.source(evidence.json_bytes(fake), 'users.json')
        with self.assertRaisesRegex(TaskError, 'Credential material'):
            evidence._public_bytes(path)
        # Even an empty credential envelope cannot be presented as a test log.
        path.write_bytes(evidence.json_bytes({'format': fake['format'], 'users': []}))
        with self.assertRaisesRegex(TaskError, 'Credential material'):
            evidence._public_bytes(path)

    def test_nested_secret_keys_are_case_and_separator_normalized(self):
        for key in ('password_sha256', 'PasswordSHA256', 'password-sha-256', 'Pass Word Hash',
                    'AccessToken', 'ACCESS_TOKEN', 'access-token', 'Access Token',
                    'RefreshToken', 'refresh_token', 'Authorization', 'Private-Key'):
            with self.subTest(key=key):
                path = self.source(evidence.json_bytes({'response': [{'AuthorizationService': {
                    key: 'explicit-disposable-unit-test-material'}}]}))
                with self.assertRaisesRegex(TaskError, 'Credential material'):
                    evidence._public_bytes(path)

    def test_camelcase_tokens_in_json_fragments_and_authorization_logs_are_rejected(self):
        for content in (
                b"INFO AuthorizationService response: {'AccessToken': 'disposable-access-fixture'}\n",
                b'INFO response={"RefreshToken":"disposable-refresh-fixture"}\n',
                b'AuthorizationService.AccessToken = disposable-access-fixture\n',
                b'Authorization: Bearer disposable-bearer-fixture\n',
                b'authorization: Basic dW5pdC10ZXN0LW9ubHk=\n'):
            with self.subTest(content=content):
                with self.assertRaisesRegex(TaskError, 'Credential material'):
                    evidence._public_bytes(self.source(content))

    def test_plaintext_password_and_private_key_remain_rejected(self):
        for content in (b'{"password":"disposable-password-fixture"}',
                        b'Password=disposable-password-fixture\n',
                        b'-----BEGIN PRIVATE KEY-----\nunit-test-only\n-----END PRIVATE KEY-----'):
            with self.subTest(content=content):
                with self.assertRaisesRegex(TaskError, 'Credential material'):
                    evidence._public_bytes(self.source(content))

    def test_boot_fingerprint_public_certificate_and_password_documentation_are_allowed(self):
        structured = evidence.json_bytes({'boot_id': 'disposable-boot-id', 'fingerprint': 'a' * 64,
            'certificate_sha256': 'b' * 64, 'public_certificate': '-----BEGIN CERTIFICATE-----\nunit-test-only'})
        self.assertEqual(evidence._public_bytes(self.source(structured)), structured)
        prose = (b'Documentation mentions password handling and AuthorizationService tokens.\n'
                 b'Password: a documented authentication concept. AccessToken retrieval is documented.\n'
                 b'boot_id=disposable-boot-id fingerprint=aaaaaaaa\n')
        self.assertEqual(evidence._public_bytes(self.source(prose)), prose)


class SonicationSiLAEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence.EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=evidence.EVIDENCE, prefix='s09-sila-evidence-test-')
        cls.directory = Path(cls.temporary.name)
        cls.runtime = SonicationRuntime(cls.directory / 'runtime')
        cls.run_id = 'TEST.S09.SiLAEvidence'
        try:
            cls.runtime.command('CreateRun', {'run_identifier': cls.run_id,
                'request_identifier': 'create', 'scenario_identifier': 'normal'}, 'offline.test.principal')
            cls.runtime.command('RunUntilDecision', {'run_identifier': cls.run_id,
                'request_identifier': 'run'}, 'offline.test.principal')
        except BaseException:
            cls.runtime.close(); cls.temporary.cleanup()
            raise
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()
        cls.temporary.cleanup()

    def export(self, **options):
        type(self).counter += 1
        return evidence.export_bundle(self.runtime, self.directory / ('bundle-%03d' % self.counter), **options)

    def change_file(self, path, name, content):
        manifest = evidence.read_json(path)
        target = path.parent / name
        target.write_bytes(content)
        for record in manifest['files']:
            if record['path'] == name:
                record.update(sha256=evidence.sha(content), bytes=len(content))
        path.write_bytes(evidence.json_bytes(manifest))

    def public_identity(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        path = self.directory / 'public.crt'
        if not path.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'Unit-test public identity')])
            now = datetime.now(timezone.utc)
            certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier('1.3.6.1.4.1.58583'),
                               self.runtime.server_uuid.encode()), critical=False)
                .sign(key, hashes.SHA256()))
            path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        return {'server_uuid': self.runtime.server_uuid, 'boot_id': self.runtime.boot_id,
            'bind': '127.0.0.1', 'port': 12345, 'tls': True, 'certificate': str(path)}

    def test_export_preserves_sql_strings_originals_definition_and_chain(self):
        with Journal(self.runtime.journal_path) as journal:
            before = journal.connection.execute('SELECT sequence, document, sha256 FROM events ORDER BY sequence').fetchall()
        path = self.export()
        result = evidence.check_manifest(path)
        archive, events, artifacts = evidence.verify_journal(path.parent / result['runs'][0]['journal'])
        self.assertEqual([(row['sequence'], row['document'], row['sha256']) for row in archive['events']], before)
        self.assertEqual(archive['chain_head_sha256'], events[-1]['sha256'])
        self.assertIn(events[-1]['definition_sha256'], artifacts)
        with Journal(self.runtime.journal_path) as journal:
            after = journal.connection.execute('SELECT sequence, document, sha256 FROM events ORDER BY sequence').fetchall()
            for checksum, original in artifacts.items():
                self.assertEqual(journal.artifact(checksum), original.read_bytes())
        self.assertEqual(after, before)

    def test_offline_export_keeps_all_domain_and_network_execution_flags_false(self):
        path = self.export()
        value = evidence.check_manifest(path)
        self.assertEqual(value['format'], 'solidcraftbot.s09-sila2-evidence/1')
        self.assertFalse(value['claims']['network_executed'])
        self.assertFalse(value['claims']['sila_executed'])
        self.assertFalse(value['claims']['visually_reviewed'])
        self.assertTrue(value['claims']['test_fixture_only'])
        report = evidence.read_json(path.parent / value['runs'][0]['report'])
        self.assertFalse(report['network_executed'])
        self.assertFalse(report['hardware_executed'])
        self.assertFalse(report['reference_success'])
        self.assertEqual(report['remaining'][next(iter(report['sonication']['intents'].values()))['material_after_id']]['value'], 295)

    def test_public_identity_and_logs_cannot_turn_inprocess_receipts_into_network_proof(self):
        log = self.directory / 'offline-test.log'
        log.write_bytes(b'Offline test fixture only. No loopback executed.\nRan 1 test\nOK\n')
        path = self.export(public_identity=self.public_identity(), test_logs={'offline': log})
        value = evidence.check_manifest(path)
        self.assertFalse(value['claims']['network_executed'])
        self.assertEqual(value['loopback_evidence']['receipts'], [])
        self.assertEqual(value['loopback_evidence']['test_log_sha256']['offline'], evidence.sha(log.read_bytes()))

    def test_header_cannot_claim_network_or_hardware_without_bound_receipts(self):
        for claim in ('network_executed', 'sila_executed', 'hardware_executed', 'visually_reviewed'):
            with self.subTest(claim=claim):
                path = self.export(); value = evidence.read_json(path)
                value['claims'][claim] = True
                path.write_bytes(evidence.json_bytes(value))
                with self.assertRaisesRegex(TaskError, 'claims differ'):
                    evidence.check_manifest(path)

    def test_three_time_axes_are_explicit_and_no_measured_runtime_is_invented(self):
        path = self.export(); value = evidence.check_manifest(path)
        scenes = evidence.read_json(path.parent / value['scenes'])
        for index, scene in enumerate(scenes):
            self.assertNotIn('measured_fixture_elapsed_s', scene)
            self.assertEqual(scene['video_time_s'], index * 0.5)
            self.assertIsInstance(scene['capture_times']['journal_time_unix_s'], (int, float))
            self.assertIn('not measured process duration', scene['capture_times']['basis'])
        text = evidence.scene_text(scenes[-1], value['claims'])
        for phrase in ('Schematische Darstellung', 'test_fixture', 'nicht nachgewiesen',
                       'ROS/Hardware/Roboterbewegung nicht ausgeführt', 'keine Prozessdauer',
                       '0.5 s/Ereignis', '295', '150', '450'):
            self.assertIn(phrase, text)
        self.assertNotIn('GEMESSENE lokale Fixture-Laufzeit', text)

    def test_source_closure_includes_runtime_control_contract_standard_provenance_and_generated_fdl(self):
        path = self.export(); value = evidence.check_manifest(path)
        self.assertTrue(evidence.CORE_SOURCES <= set(value['source_snapshots']))
        profile = evidence.read_json(path.parent / value['profile'])
        for item in profile['standard_features']:
            name = value['source_snapshots'][item['source']]
            self.assertEqual(evidence.sha((path.parent / name).read_bytes()), item['source_sha256'])
        self.assertIn('CutRunInputSonicationWorkflow', (path.parent / value['generated_fdl']).read_text())

    def test_archived_bytes_remain_checkable_when_checkout_sources_are_unavailable(self):
        path = self.export()
        original = Path.read_bytes
        def read(candidate):
            if candidate.is_relative_to(ROOT / 'scripts') or candidate.is_relative_to(ROOT / 'model'):
                raise OSError('Current checkout is deliberately unavailable')
            return original(candidate)
        with patch.object(Path, 'read_bytes', read):
            self.assertEqual(evidence.check_manifest(path)['format'], evidence.FORMAT)

    def test_one_byte_change_to_original_or_source_or_raw_journal_fails(self):
        for selection in ('original', 'source', 'journal'):
            with self.subTest(selection=selection):
                path = self.export(); value = evidence.read_json(path)
                if selection == 'original':
                    name = next(row['path'] for row in value['files'] if row['role'] == 'journal_original')
                elif selection == 'source':
                    name = value['source_snapshots']['scripts/sonication_sila2_runtime.py']
                else:name = value['runs'][0]['journal']
                target = path.parent / name
                target.write_bytes(target.read_bytes() + b'!')
                with self.assertRaisesRegex(TaskError, 'checksum'):
                    evidence.check_manifest(path)

    def test_rehashed_export_cannot_hide_changed_raw_document_or_chain_head(self):
        for selection in ('document', 'head'):
            with self.subTest(selection=selection):
                path = self.export(); manifest = evidence.read_json(path)
                name = manifest['runs'][0]['journal']; archive = evidence.read_json(path.parent / name)
                if selection == 'document':archive['events'][1]['document'] += ' '
                else:archive['chain_head_sha256'] = '0' * 64
                self.change_file(path, name, evidence.json_bytes(archive))
                with self.assertRaisesRegex(TaskError, 'document checksum|chain head'):
                    evidence.check_manifest(path)

    def test_rehashed_report_cannot_change_quantity_or_transport_identity(self):
        for selection in ('quantity', 'principal', 'network_executed', 'reference_success',
                          'preparation_complete', 'preparation_execution_ready', 'biochemical_protocol_executed'):
            with self.subTest(selection=selection):
                path = self.export(); manifest = evidence.read_json(path)
                name = manifest['runs'][0]['report']; report = evidence.read_json(path.parent / name)
                if selection == 'quantity':
                    material = next(iter(report['sonication']['intents'].values()))['material_after_id']
                    report['remaining'][material]['value'] = 300
                elif selection == 'principal':
                    report['transport_receipts']['network']['commands']['create']['principal'] = 'forged.principal'
                else:report[selection] = True
                self.change_file(path, name, evidence.json_bytes(report))
                with self.assertRaises(TaskError):
                    evidence.check_manifest(path)

    def test_source_omission_generated_command_mutation_and_unlisted_files_fail(self):
        path = self.export(); manifest = evidence.read_json(path)
        del manifest['runs'][0]['source_snapshots']['scripts/manual_tasks.py']
        path.write_bytes(evidence.json_bytes(manifest))
        with self.assertRaisesRegex(TaskError, 'domain source closure'):
            evidence.check_manifest(path)
        path = self.export(); manifest = evidence.read_json(path)
        name = manifest['generated_fdl']; xml = (path.parent / name).read_bytes()
        self.change_file(path, name, xml.replace(b'<Identifier>CreateRun</Identifier>', b'<Identifier>ForgedRun</Identifier>'))
        with self.assertRaisesRegex(TaskError, 'command surface'):
            evidence.check_manifest(path)
        path = self.export(); (path.parent / 'unlisted.txt').write_bytes(b'Not inventoried')
        with self.assertRaisesRegex(TaskError, 'inventory'):
            evidence.check_manifest(path)

    def test_replayed_or_rewritten_material_effect_fails_semantic_validation(self):
        path = self.export(); manifest = evidence.read_json(path)
        unused, events, unused_artifacts = evidence.verify_journal(path.parent / manifest['runs'][0]['journal'])
        identity = next(key for key, item in events[-1]['state']['bookings'].items() if item['outcome'] == 'performed')
        changed = copy.deepcopy(events)
        changed[-1]['state']['bookings'][identity]['actual_inputs'][0]['quantity']['value'] += 1
        with self.assertRaisesRegex(TaskError, 'effect was repeated or rewritten'):
            evidence._verify_effects(changed)

    def test_all_size_findings_and_conflicts_are_visible_independent_of_key_order(self):
        path = self.export(); manifest = evidence.check_manifest(path)
        scene = evidence.read_json(path.parent / manifest['scenes'])[-1]
        records = scene['intent']['size_records']
        original = next(iter(records.values()))
        bad = copy.deepcopy(original)
        bad['observation'].update(size_id='A.ContradictorySize', minimum_bp=12000, maximum_bp=15000)
        bad['fixture_range_conformant'] = False
        records['A.ContradictorySize'] = bad
        text = evidence.scene_text(scene, manifest['claims'])
        for phrase in (*records, '12000', '15000', '150', '450', 'WIDERSPRUCH; S09-Abschluss gesperrt.'):
            self.assertIn(phrase, text)
        self.assertEqual(text, evidence.scene_text(json.loads(evidence.json_bytes(scene)), manifest['claims']))

    def test_credentials_and_private_identity_are_never_copied(self):
        fake_users = {'format': 'solidcraftbot.sonication-sila-users/1', 'users': [{
            'username': 'disposable-user', 'role': 'operator', 'salt': 'f00d' * 8,
            'iterations': 200000, 'password_sha256': 'deadbeef' * 8}]}
        for filename, content in (
                ('unsafe-test.log', b'{"password":"unit-test-secret-that-must-not-be-copied"}'),
                ('users.json', evidence.json_bytes(fake_users)),
                ('token-test.log', b'AuthorizationService response: {"AccessToken":"disposable-fixture"}')):
            with self.subTest(filename=filename):
                source = self.directory / filename
                source.write_bytes(content)
                with self.assertRaisesRegex(TaskError, 'Credential'):
                    self.export(test_logs={'unsafe': source})
                bundle = self.directory / ('bundle-%03d' % self.counter)
                self.assertFalse((bundle / 'inputs/test-logs/unsafe.log').exists())
        identity = self.public_identity(); identity['password'] = 'forbidden'
        with self.assertRaisesRegex(TaskError, 'Credentials'):
            self.export(public_identity=identity)

    def test_escape_existing_bundle_and_wrong_public_server_are_rejected(self):
        with self.assertRaises(TaskError):
            evidence.export_bundle(self.runtime, ROOT / 'docs/media/forbidden-s09')
        path = self.export()
        with self.assertRaises(TaskError):
            evidence.export_bundle(self.runtime, path.parent)
        identity = self.public_identity(); identity['server_uuid'] = 'another-server'
        with self.assertRaisesRegex(TaskError, 'loopback endpoint'):
            self.export(public_identity=identity)

    def test_cli_check_reads_manifest_and_keeps_artifacts_unchanged(self):
        path = self.export(); before = path.read_bytes()
        checked = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/sonication_sila2_evidence.py'),
            '--check', str(path)], text=True, capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn('"checked": true', checked.stdout)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
