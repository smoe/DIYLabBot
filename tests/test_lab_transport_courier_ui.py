"""Real browser behavior; server authority and TLS are tested separately."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CourierBrowserTests(unittest.TestCase):
    def test_explicit_role_actions_and_persistent_exact_retry_in_chromium(self):
        node = shutil.which('node')
        module = os.environ.get('SOLIDCRAFTBOT_PLAYWRIGHT')
        bundled = Path('/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright')
        if not module and bundled.is_dir(): module = str(bundled)
        chrome = os.environ.get('SOLIDCRAFTBOT_CHROME')
        installed = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        if not chrome and installed.is_file(): chrome = str(installed)
        if not node or not module or not chrome:
            self.skipTest('Node, Playwright and Chromium required; configure SOLIDCRAFTBOT_PLAYWRIGHT/SOLIDCRAFTBOT_CHROME')
        (ROOT / 'exports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='courier-browser-', dir=ROOT / 'exports') as temp:
            result = subprocess.run([node, str(ROOT / 'tests/check_lab_transport_courier.cjs'), module, chrome,
                                     str(Path(temp) / 'courier.png')], cwd=ROOT, capture_output=True,
                                    text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads(result.stdout)
            self.assertTrue(report['passed'])
            self.assertTrue(report['accountBoundPendingIntent'])
            self.assertTrue(report['exactRetryAfterUncommittedLoss'])
            self.assertTrue(report['explicitOwnerReconciliation'])
            self.assertTrue(report['malformedPendingBlocksNewStatements'])
            self.assertTrue(report['explicitRoutePreparationAndDispatchWithExactReloadRetry'])
            self.assertTrue(report['receiptIntentSubjectGrantAndDigestVerified'])
            self.assertTrue(report['missingWebCryptoPreservesPending'])
            self.assertTrue(report['failedSessionFetchClearsPartialLogin'])


if __name__ == '__main__':
    unittest.main()
