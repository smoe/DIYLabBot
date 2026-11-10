"""Persisted TLS identities fail closed without silently replacing certificates."""
import datetime
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
AVAILABLE = importlib.util.find_spec('sila') is not None and importlib.util.find_spec('cryptography') is not None


@unittest.skipUnless(AVAILABLE, 'Install requirements/sila2-test.in')
class TLSIdentityTests(unittest.TestCase):
    def setUp(self):
        from cf01_sila2_server import CF01Server
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.server = object.__new__(CF01Server)
        self.server.runtime = types.SimpleNamespace(store=types.SimpleNamespace(server_uuid=str(uuid.uuid4())))
        self.original, self.key = self.server._certificate(self.root, '127.0.0.1')

    def tearDown(self):
        self.directory.cleanup()

    def test_persistent_identity_and_private_key_pairing(self):
        self.assertEqual(self.server._certificate(self.root, '127.0.0.1'), (self.original, self.key))
        from sila.server import create_certificate
        other = create_certificate(str(uuid.uuid4()), ip_addresses=['127.0.0.1'])
        (self.root / 'server.key').write_bytes(other.pem_private_key)
        with self.assertRaisesRegex(ValueError, 'do not match'):
            self.server._certificate(self.root, '127.0.0.1')
        self.assertEqual((self.root / 'server.crt').read_bytes(), self.original)

    def test_wrong_uuid_and_incomplete_identity_are_not_replaced(self):
        self.server.runtime.store.server_uuid = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, 'different SiLA server UUID'):
            self.server._certificate(self.root, '127.0.0.1')
        self.assertEqual((self.root / 'server.crt').read_bytes(), self.original)
        (self.root / 'server.key').unlink()
        with self.assertRaisesRegex(ValueError, 'Incomplete TLS identity'):
            self.server._certificate(self.root, '127.0.0.1')

    def test_expired_and_future_certificates_are_refused(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        original = x509.load_pem_x509_certificate(self.original)
        key = serialization.load_pem_private_key(self.key, password=None)
        now = datetime.datetime.now(datetime.timezone.utc)
        for start, end in [(-2, -1), (1, 2)]:
            with self.subTest(start=start):
                builder = (x509.CertificateBuilder().subject_name(original.subject).issuer_name(original.issuer)
                    .public_key(original.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now + datetime.timedelta(days=start))
                    .not_valid_after(now + datetime.timedelta(days=end)))
                for extension in original.extensions:
                    builder = builder.add_extension(extension.value, extension.critical)
                invalid = builder.sign(key, original.signature_hash_algorithm).public_bytes(serialization.Encoding.PEM)
                (self.root / 'server.crt').write_bytes(invalid)
                with self.assertRaisesRegex(ValueError, 'valid'):
                    self.server._certificate(self.root, '127.0.0.1')
                self.assertEqual((self.root / 'server.crt').read_bytes(), invalid)
