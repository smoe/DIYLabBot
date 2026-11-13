"""Credential accounts, token lifetime and detached local role grants."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lab_transport_access import Access, AuthError, credential
from manual_tasks import TaskError


class TransportAccessTests(unittest.TestCase):
    PASSWORD = 'SYN.Only.Fixture.Password'
    SERVER = '00000000-0000-4000-8000-000000000001'

    def setUp(self):
        self.now = 0.0
        self.grants = [{'id': 'Courier', 'kind': 'agent', 'resource_id': 'AgentHuman'}]
        self.user = credential('courier@example.test', self.PASSWORD, 'SYN.Human.Courier', self.grants)
        self.access = Access([self.user], self.SERVER, clock=lambda: self.now)

    def login(self):
        return self.access.login(self.user['username'], self.PASSWORD, self.SERVER)

    def test_private_record_contains_hash_salt_and_no_plaintext_password(self):
        self.assertNotIn(self.PASSWORD, str(self.user))
        self.assertNotIn('password', self.user)
        self.assertNotEqual(self.user['password_sha256'], self.PASSWORD)
        self.assertGreaterEqual(self.user['iterations'], 600000)

    def test_authenticated_subject_principal_and_grants_are_server_context(self):
        result = self.login()
        context = self.access.authorize(result['access_token'])
        self.assertEqual(context, {'subject': self.user['username'], 'principal': 'SYN.Human.Courier',
                                   'grants': self.grants})
        context['grants'][0]['kind'] = 'owner'
        self.assertEqual(self.access.authorize(result['access_token'])['grants'], self.grants)
        self.assertNotIn(result['access_token'], str(self.access.tokens))

    def test_wrong_server_password_or_account_is_not_authenticated(self):
        for username, password, server in [(self.user['username'], 'incorrect', self.SERVER),
                                            ('unknown', self.PASSWORD, self.SERVER),
                                            (self.user['username'], self.PASSWORD, 'other-server')]:
            with self.subTest(username=username), self.assertRaises(AuthError) as rejected:
                self.access.login(username, password, server)
            self.assertNotIn(self.PASSWORD, str(rejected.exception))

    def test_token_deadline_uses_only_wall_clock_and_cannot_be_refreshed_by_reads(self):
        token = self.login()['access_token']
        self.now = 899
        self.access.authorize(token)
        self.now = 900
        with self.assertRaises(AuthError): self.access.authorize(token)

    def test_logout_revokes_only_the_selected_bearer_token(self):
        first = self.login()['access_token']; second = self.login()['access_token']
        self.access.logout(first)
        with self.assertRaises(AuthError): self.access.authorize(first)
        self.assertEqual(self.access.authorize(second)['principal'], 'SYN.Human.Courier')

    def test_accounts_may_share_domain_principal_but_keep_distinct_subjects(self):
        other = credential('second-courier', self.PASSWORD, self.user['principal'], self.grants)
        access = Access([self.user, other], self.SERVER)
        first = access.authorize(access.login(self.user['username'], self.PASSWORD, self.SERVER)['access_token'])
        second = access.authorize(access.login(other['username'], self.PASSWORD, self.SERVER)['access_token'])
        self.assertEqual(first['principal'], second['principal'])
        self.assertNotEqual(first['subject'], second['subject'])

    def test_config_rejects_weak_duplicate_or_ambiguous_grants(self):
        for change in [lambda u: u.update(iterations=True), lambda u: u.update(iterations=1),
                       lambda u: u['grants'][0].update(kind='administrator'),
                       lambda u: u['grants'].append(copy.deepcopy(u['grants'][0])),
                       lambda u: u.update(password='plaintext')]:
            user = copy.deepcopy(self.user); change(user)
            with self.assertRaises(TaskError): Access([user], self.SERVER)
        with self.assertRaises(TaskError): Access([self.user, self.user], self.SERVER)

    def test_repeated_failed_login_has_a_bounded_cooldown(self):
        for _ in range(5):
            with self.assertRaises(AuthError): self.access.login(self.user['username'], 'incorrect', self.SERVER)
        with self.assertRaises(AuthError): self.login()
        self.now = 31
        self.assertIn('access_token', self.login())

    def test_tokens_are_not_recovered_by_a_new_authentication_process(self):
        token = self.login()['access_token']
        restarted = Access([self.user], self.SERVER)
        with self.assertRaises(AuthError): restarted.authorize(token)


if __name__ == '__main__':
    unittest.main()
