"""CLI path checks precede root creation and remote command dispatch."""
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/run_sonication_sila2.py'


class SonicationSiLACliTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='s09-sila-cli-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.blocker = self.folder / 'existing-file'
        self.blocker.write_text('preserve this original')

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *arguments):
        return subprocess.run([sys.executable, str(CLI), *map(str, arguments)], cwd=ROOT,
            capture_output=True, text=True, timeout=15,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})

    def test_help_is_available_in_both_languages_without_network_dependencies(self):
        german = self.cli('--language', 'de', '--help')
        english = self.cli('--language', 'en', '--help')
        self.assertEqual(german.returncode, 0, german.stderr)
        self.assertEqual(english.returncode, 0, english.stderr)
        self.assertIn('synthetischer TLS-Server', german.stdout)
        self.assertIn('synthetic TLS server', english.stdout)
        self.assertIn('scenario', english.stdout)

    def test_invalid_output_ancestors_are_rejected_before_endpoint_or_login_reads(self):
        for command in ('scenario', 'command', 'status', 'report'):
            for suffix in ('result.json', 'missing/deeper/result.json'):
                with self.subTest(command=command, suffix=suffix):
                    args = [command, '--ready-file', self.folder / 'missing-ready.json',
                            '--login-input', self.folder / 'missing-login.json',
                            '--out', self.blocker / suffix]
                    if command in {'scenario', 'command'}:
                        args += ['--run-id', 'Fixture.Network.Cli']
                    if command == 'command':
                        args += ['--name', 'RunUntilDecision', '--request-id', 'request-1']
                    result = self.cli(*args)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn('Output parent must be a directory: ' + str(self.blocker), result.stderr)
                    self.assertFalse((self.folder / 'missing').exists())
        self.assertEqual(self.blocker.read_text(), 'preserve this original')

    def test_existing_output_is_preserved_before_endpoint_reads(self):
        result = self.cli('scenario', '--ready-file', self.folder / 'missing-ready.json',
            '--login-input', self.folder / 'missing-login.json', '--run-id', 'Fixture.Network.Cli',
            '--out', self.blocker)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Output already exists', result.stderr)
        self.assertEqual(self.blocker.read_text(), 'preserve this original')

    def test_serve_ready_output_is_preflighted_before_runtime_tls_or_credentials(self):
        directory, tls = self.folder / 'server', self.folder / 'tls'
        result = self.cli('serve', '--directory', directory, '--tls-directory', tls,
            '--credentials', self.folder / 'missing-users.json',
            '--ready-file', self.blocker / 'missing' / 'ready.json')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Output parent must be a directory', result.stderr)
        self.assertFalse(directory.exists())
        self.assertFalse(tls.exists())

    def test_init_output_and_directory_ancestors_precede_any_write(self):
        source = self.folder / 'input.json'
        source.write_text(json.dumps([{'username': 'operator', 'password': 'fixture-only-password', 'role': 'operator'}]))
        source.chmod(0o600)
        directory = self.folder / 'server'
        result = self.cli('init', '--directory', directory, '--credentials-input', source,
                          '--credentials', self.blocker / 'deep' / 'users.json')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Output parent must be a directory', result.stderr)
        self.assertFalse(directory.exists())
        credentials = self.folder / 'not-written.json'
        result = self.cli('init', '--directory', self.blocker / 'deep' / 'server',
                          '--credentials-input', source, '--credentials', credentials)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Output parent must be a directory', result.stderr)
        self.assertFalse(credentials.exists())

    def test_init_creates_private_hashed_credentials_and_preserves_existing_identity(self):
        source = self.folder / 'input.json'
        password = 'fixture-only-initialization-password'
        source.write_text(json.dumps([{'username': 'operator', 'password': password, 'role': 'operator'}]))
        source.chmod(0o600)
        directory, credentials = self.folder / 'server', self.folder / 'users.json'
        result = self.cli('init', '--directory', directory, '--credentials-input', source,
                          '--credentials', credentials)
        self.assertEqual(result.returncode, 0, result.stderr)
        ready = json.loads(result.stdout)
        self.assertTrue(ready['simulation_only'])
        self.assertFalse(ready['hardware_available'])
        self.assertEqual(stat.S_IMODE(credentials.stat().st_mode), 0o600)
        users = json.loads(credentials.read_text())
        self.assertEqual(users['format'], 'solidcraftbot.sonication-sila-users/1')
        self.assertNotIn(password, credentials.read_text())
        self.assertNotIn(password, result.stdout + result.stderr)
        before = credentials.read_bytes()
        identity = (directory / 'identity.json').read_bytes()
        repeated = self.cli('init', '--directory', directory, '--credentials-input', source,
                            '--credentials', credentials)
        self.assertEqual(repeated.returncode, 1)
        self.assertEqual(credentials.read_bytes(), before)
        self.assertEqual((directory / 'identity.json').read_bytes(), identity)


if __name__ == '__main__':
    unittest.main()
