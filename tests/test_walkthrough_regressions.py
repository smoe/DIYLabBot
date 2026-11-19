"""Exercise the CI exit status with independent passing and incomplete suites."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT/'scripts/check_walkthrough_regressions.py'


class StrictWalkthroughTests(unittest.TestCase):
    def invoke(self, source, pattern='test_fixture.py'):
        # Reports stay in the same ignored area used by actual CI runs.
        (ROOT/'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='walkthrough-runner-', dir=ROOT/'exports') as directory:
            fixture = Path(directory)
            (fixture/'test_fixture.py').write_text(source, encoding='utf-8')
            report = fixture/'result.json'
            result = subprocess.run(
                [sys.executable, str(RUNNER), '--start-directory', str(fixture),
                 '--pattern', pattern, '--report', str(report)],
                text=True, capture_output=True, cwd=ROOT)
            return result, json.loads(report.read_text())

    def test_passing_suite_runs_and_succeeds(self):
        result, report = self.invoke('import unittest\nclass Fixture(unittest.TestCase):\n'
                                     '    def test_pass(self): self.assertEqual(2 + 2, 4)\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report['passed'])
        self.assertEqual(report['tests_run'], 1)
        self.assertEqual(report['skipped'], 0)

    def test_skipped_suite_is_not_a_success(self):
        result, report = self.invoke('import unittest\nclass Fixture(unittest.TestCase):\n'
                                     '    @unittest.skip("native proof missing")\n'
                                     '    def test_native(self): raise AssertionError("must not run")\n')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['skipped'], 1)
        self.assertEqual(report['skipped_tests'][0]['reason'], 'native proof missing')
        self.assertIn('skips are failures', result.stderr)

    def test_missing_optional_dependency_cannot_silently_skip(self):
        result, report = self.invoke('import unittest\nclass Fixture(unittest.TestCase):\n'
                                     '    def test_schema(self):\n'
                                     '        try: import nonexistent_walkthrough_validator_fixture\n'
                                     '        except ImportError: self.skipTest("validator unavailable")\n')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['skipped'], 1)

    def test_real_failures_and_import_errors_fail(self):
        for source, key in [
            ('import unittest\nclass Fixture(unittest.TestCase):\n'
             '    def test_failure(self): self.fail("fixture failure")\n', 'failures'),
            ('raise RuntimeError("fixture import error")\n', 'errors'),
        ]:
            with self.subTest(key=key):
                result, report = self.invoke(source)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(report['passed'])
                self.assertEqual(report[key], 1)

    def test_empty_discovery_does_not_claim_success(self):
        result, report = self.invoke('import unittest\n', pattern='test_absent_*.py')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['tests_run'], 0)
        self.assertIn('selected no tests', result.stderr)


if __name__ == '__main__':
    unittest.main()
