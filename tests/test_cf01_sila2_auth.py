"""Scopes, revocation and idle expiry use wall time independently of process time."""
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cf01_sila2_auth import Access, credential, TOKEN_LIFETIME_S


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.feature = 'org.solidcraftbot/centrifugation/CentrifugeControl/v2'
        self.access = Access([credential('operator', 'test-only-password', 'operator'),
                              credential('observer', 'test-only-password', 'observer')],
                             'server', [self.feature, 'another-feature'], clock=lambda: self.now)

    def login(self, username='operator', features=None):
        return self.access.login(username, 'test-only-password', 'server', features or [self.feature])[0]

    def handler(self, name, feature=None):
        return types.SimpleNamespace(identifier=name, feature=types.SimpleNamespace(fully_qualified_identifier=feature or self.feature))

    def test_feature_scope_server_and_role(self):
        token = self.login()
        self.assertEqual(self.access.authorize(token, self.handler('RunCentrifuge')), 'operator')
        with self.assertRaises(PermissionError):
            self.access.authorize(token, self.handler('GetStatus', 'another-feature'))
        observer = self.login('observer')
        self.assertEqual(self.access.authorize(observer, self.handler('GetStatus')), 'observer')
        with self.assertRaises(PermissionError):
            self.access.authorize(observer, self.handler('RunCentrifuge'))
        with self.assertRaises(PermissionError):
            self.access.login('operator', 'test-only-password', 'other-server', [])
        with self.assertRaises(PermissionError):
            self.access.login('operator', 'wrong-password', 'server', [])

    def test_idle_deadline_renewal_expiry_and_revocation(self):
        token = self.login()
        self.now = TOKEN_LIFETIME_S - 1
        self.access.authorize(token)
        self.now += TOKEN_LIFETIME_S - 1
        self.access.authorize(token)
        self.now += TOKEN_LIFETIME_S
        with self.assertRaises(PermissionError):
            self.access.authorize(token)
        fresh = self.login()
        self.access.logout(fresh)
        with self.assertRaises(PermissionError):
            self.access.authorize(fresh)
